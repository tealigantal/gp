from __future__ import annotations

"""The only product-facing persistence boundary for GP.

This module intentionally has no readers for gateway.db, Book/Run JSON, or V1/V2
recommendation artifacts.  A missing or invalid row is an integrity failure, never
an invitation to fall back to legacy state.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .contracts.objects import DayBook, LiveSlotArtifact, MarketBook
from .core.paths import store_dir
from .runtime.utils import gen_id, now_iso


SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA = "RecommendationSnapshot.v1"


class AgentStoreError(RuntimeError):
    pass


class SnapshotIntegrityError(AgentStoreError):
    pass


class MigrationError(AgentStoreError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def agent_db_path() -> Path:
    path = Path(os.getenv("GP_AGENT_DB") or str(store_dir() / "agent.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class StoredSnapshot:
    snapshot_id: str
    schema_version: str
    as_of: str
    decision: str
    tradeable: bool
    payload: dict[str, Any]
    payload_hash: str
    created_at: str


class AgentStore:
    def __init__(self, path: Path | None = None):
        self.path = path or agent_db_path()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def initialize(self) -> None:
        checksum = _hash({"schema": SCHEMA_VERSION, "snapshot_schema": SNAPSHOT_SCHEMA})
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)"
            )
            existing = conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall()
            if existing and (len(existing) != 1 or int(existing[0]["version"]) != SCHEMA_VERSION or existing[0]["checksum"] != checksum):
                raise MigrationError("agent_db_schema_mismatch")
            # sqlite3.executescript performs an implicit commit, which would
            # break the all-or-nothing migration transaction.  Keep each DDL
            # statement inside this explicit BEGIN IMMEDIATE instead.
            for statement in (
                "CREATE TABLE IF NOT EXISTS recommendation_snapshots(snapshot_id TEXT PRIMARY KEY,schema_version TEXT NOT NULL,as_of TEXT NOT NULL,decision TEXT NOT NULL,tradeable INTEGER NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS current_snapshot(singleton INTEGER PRIMARY KEY CHECK(singleton=1),snapshot_id TEXT NOT NULL REFERENCES recommendation_snapshots(snapshot_id))",
                "CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,active_snapshot_id TEXT NOT NULL REFERENCES recommendation_snapshots(snapshot_id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS turns(turn_id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,seq INTEGER NOT NULL,client_turn_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','assistant')),content TEXT NOT NULL,snapshot_id TEXT NOT NULL REFERENCES recommendation_snapshots(snapshot_id),payload_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(session_id,seq),UNIQUE(session_id,client_turn_id,role))",
                "CREATE TABLE IF NOT EXISTS claims(claim_id TEXT PRIMARY KEY,turn_id TEXT NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)",
            ):
                conn.execute(statement)
            if not existing:
                conn.execute("INSERT INTO schema_migrations(version,applied_at,checksum) VALUES(?,?,?)", (SCHEMA_VERSION, now_iso(), checksum))
            conn.execute("COMMIT")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def publish_book(self, book: MarketBook) -> StoredSnapshot:
        payload = {"book": book.model_dump(mode="json")}
        decision = "recommend" if bool(book.daybook.picks) else "no_trade"
        snapshot_id = str(book.artifact_id or book.book_version)
        if not snapshot_id:
            raise SnapshotIntegrityError("snapshot_id_missing")
        as_of = str(book.updated_at or "")
        if not as_of:
            raise SnapshotIntegrityError("snapshot_as_of_missing")
        record = StoredSnapshot(
            snapshot_id=snapshot_id,
            schema_version=SNAPSHOT_SCHEMA,
            as_of=as_of,
            decision=decision,
            tradeable=bool(book.publish_allowed and book.daybook.tradeable),
            payload=payload,
            payload_hash=_hash(payload),
            created_at=now_iso(),
        )
        self.publish_snapshot(record)
        return record

    def publish_runtime_artifact(self, daybook: DayBook, artifact: LiveSlotArtifact) -> StoredSnapshot:
        """Project the in-memory decision result into the sole persisted product snapshot."""
        if artifact.daybook_effective_day != daybook.trading_day:
            raise SnapshotIntegrityError("snapshot_trade_day_mismatch")
        allowed = {pick.symbol for pick in [*daybook.picks, *daybook.reserve_picks]}
        if any(entry.symbol not in allowed for entry in artifact.board):
            raise SnapshotIntegrityError("snapshot_board_outside_daybook")
        if {entry.symbol for entry in artifact.board} != {pick.symbol for pick in daybook.picks}:
            raise SnapshotIntegrityError("snapshot_board_pick_mismatch")
        data_status = str((artifact.provider_meta or {}).get("data_status") or "daily_plan")
        book = MarketBook(
            trading_day=artifact.trade_day,
            book_version=artifact.artifact_id,
            updated_at=artifact.updated_at,
            regime=daybook.regime,
            daybook=daybook,
            board=artifact.board,
            watchset=list(artifact.tracked_universe.total),
            symbol_states=artifact.symbol_states,
            portfolio_snapshot={},
            last_closed_5m=artifact.slot_at,
            side_results=[],
            artifact_id=artifact.artifact_id,
            slot_id=artifact.slot_id,
            slot_status=artifact.slot_status,
            publish_allowed=artifact.publish_allowed,
            daybook_effective_day=artifact.daybook_effective_day,
            pulse_trade_day=artifact.trade_day if artifact.slot_at else None,
            pulse_slot_at=artifact.slot_at,
            market_phase=artifact.market_phase,
            data_status=data_status,
            gate=artifact.gate,
            data_quality=artifact.data_quality,
            tracked_universe=artifact.tracked_universe,
            producer={
                "schema_version": SNAPSHOT_SCHEMA,
                "selection_policy": str((artifact.producer or {}).get("selection_policy") or "adaptive_policy_single_path"),
            },
        )
        return self.publish_book(book)

    def publish_snapshot(self, snapshot: StoredSnapshot) -> None:
        if snapshot.schema_version != SNAPSHOT_SCHEMA:
            raise SnapshotIntegrityError("snapshot_schema_unsupported")
        if snapshot.decision not in {"recommend", "no_trade"}:
            raise SnapshotIntegrityError("snapshot_decision_invalid")
        if snapshot.payload_hash != _hash(snapshot.payload):
            raise SnapshotIntegrityError("snapshot_hash_invalid")
        try:
            book = MarketBook.model_validate(dict(snapshot.payload or {}).get("book"))
        except Exception as exc:  # noqa: BLE001
            raise SnapshotIntegrityError("snapshot_book_invalid") from exc
        if str(book.artifact_id or book.book_version) != snapshot.snapshot_id:
            raise SnapshotIntegrityError("snapshot_identity_mismatch")
        if snapshot.decision == "recommend" and not book.daybook.picks:
            raise SnapshotIntegrityError("recommend_without_picks")
        if snapshot.decision == "no_trade" and book.daybook.picks:
            raise SnapshotIntegrityError("no_trade_with_picks")
        with self._transaction() as conn:
            row = conn.execute("SELECT payload_hash FROM recommendation_snapshots WHERE snapshot_id=?", (snapshot.snapshot_id,)).fetchone()
            if row is not None and row["payload_hash"] != snapshot.payload_hash:
                raise SnapshotIntegrityError("snapshot_immutable_conflict")
            if row is None:
                conn.execute(
                    "INSERT INTO recommendation_snapshots(snapshot_id,schema_version,as_of,decision,tradeable,payload_json,payload_hash,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (snapshot.snapshot_id, snapshot.schema_version, snapshot.as_of, snapshot.decision, int(snapshot.tradeable), _canonical_json(snapshot.payload), snapshot.payload_hash, snapshot.created_at),
                )
            conn.execute("INSERT INTO current_snapshot(singleton,snapshot_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET snapshot_id=excluded.snapshot_id", (snapshot.snapshot_id,))

    def _decode_snapshot(self, row: sqlite3.Row) -> StoredSnapshot:
        payload = json.loads(row["payload_json"])
        snapshot = StoredSnapshot(
            snapshot_id=row["snapshot_id"], schema_version=row["schema_version"], as_of=row["as_of"],
            decision=row["decision"], tradeable=bool(row["tradeable"]), payload=payload,
            payload_hash=row["payload_hash"], created_at=row["created_at"],
        )
        if snapshot.schema_version != SNAPSHOT_SCHEMA or _hash(payload) != snapshot.payload_hash:
            raise SnapshotIntegrityError("snapshot_corrupt")
        return snapshot

    def current_snapshot(self) -> StoredSnapshot | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT s.* FROM current_snapshot c JOIN recommendation_snapshots s ON s.snapshot_id=c.snapshot_id WHERE c.singleton=1"
            ).fetchone()
        return self._decode_snapshot(row) if row else None

    def current_book(self) -> MarketBook | None:
        snapshot = self.current_snapshot()
        if snapshot is None:
            return None
        return self.book_for_snapshot(snapshot)

    @staticmethod
    def book_for_snapshot(snapshot: StoredSnapshot) -> MarketBook:
        try:
            return MarketBook.model_validate(snapshot.payload["book"])
        except Exception as exc:  # noqa: BLE001
            raise SnapshotIntegrityError("snapshot_book_corrupt") from exc

    def load_snapshot(self, snapshot_id: str) -> StoredSnapshot | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM recommendation_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        return self._decode_snapshot(row) if row else None

    def session_snapshot(self, session_id: str) -> StoredSnapshot | None:
        """Return the immutable snapshot already bound to a conversation."""
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT s.* FROM sessions x JOIN recommendation_snapshots s ON s.snapshot_id=x.active_snapshot_id WHERE x.session_id=?",
                (session_id,),
            ).fetchone()
        return self._decode_snapshot(row) if row else None

    def commit_turn(self, *, session_id: str, client_turn_id: str, user_content: str, assistant_content: str, assistant_payload: dict[str, Any], snapshot_id: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        if not session_id or not client_turn_id or not user_content.strip():
            raise AgentStoreError("turn_identity_or_content_invalid")
        with self._transaction() as conn:
            prior = conn.execute(
                "SELECT payload_json FROM turns WHERE session_id=? AND client_turn_id=? AND role='assistant'", (session_id, client_turn_id)
            ).fetchone()
            if prior is not None:
                return json.loads(prior["payload_json"])
            snapshot = conn.execute("SELECT 1 FROM recommendation_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if snapshot is None:
                raise SnapshotIntegrityError("turn_snapshot_missing")
            ts = now_iso()
            conn.execute(
                "INSERT INTO sessions(session_id,active_snapshot_id,created_at,updated_at) VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET active_snapshot_id=excluded.active_snapshot_id,updated_at=excluded.updated_at",
                (session_id, snapshot_id, ts, ts),
            )
            seq = int(conn.execute("SELECT COALESCE(MAX(seq),0) FROM turns WHERE session_id=?", (session_id,)).fetchone()[0]) + 1
            user_turn = gen_id("turn")
            assistant_turn = gen_id("turn")
            conn.execute("INSERT INTO turns(turn_id,session_id,seq,client_turn_id,role,content,snapshot_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (user_turn, session_id, seq, client_turn_id, "user", user_content, snapshot_id, "{}", ts))
            conn.execute("INSERT INTO turns(turn_id,session_id,seq,client_turn_id,role,content,snapshot_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (assistant_turn, session_id, seq + 1, client_turn_id, "assistant", assistant_content, snapshot_id, _canonical_json(assistant_payload), ts))
            for claim in claims:
                conn.execute("INSERT INTO claims(claim_id,turn_id,payload_json,created_at) VALUES(?,?,?,?)", (str(claim.get("claim_id") or gen_id("claim")), assistant_turn, _canonical_json(claim), ts))
            return assistant_payload

    def session_turns(self, session_id: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute("SELECT turn_id,seq,role,content,snapshot_id,payload_json,created_at FROM turns WHERE session_id=? ORDER BY seq", (session_id,)).fetchall()
        result = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            result.append({"turn_id": row["turn_id"], "seq": int(row["seq"]), "role": row["role"], "content": row["content"], "snapshot_id": row["snapshot_id"], "payload": payload, "created_at": row["created_at"]})
        return result

    def stats(self) -> dict[str, Any]:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute("SELECT (SELECT COUNT(*) FROM sessions) sessions,(SELECT COUNT(*) FROM turns) turns,(SELECT COUNT(*) FROM recommendation_snapshots) snapshots").fetchone()
            current = conn.execute("SELECT snapshot_id FROM current_snapshot WHERE singleton=1").fetchone()
        return {"sessions": int(row["sessions"]), "turns": int(row["turns"]), "snapshots": int(row["snapshots"]), "current_snapshot_id": current["snapshot_id"] if current else None, "path": str(self.path)}
