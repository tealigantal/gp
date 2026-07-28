from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import uuid

from ..core.paths import store_dir


MARKET_RUN_SCHEMA = "market_runs.v1"
RUN_PENDING = "pending"
RUN_PROBING = "probing"
RUN_FETCHING = "fetching"
RUN_RETRY_WAIT = "retry_wait"
RUN_COMPLETE = "complete"


def market_run_database_path() -> Path:
    configured = os.getenv("GP_MARKET_RUN_DB", "").strip()
    return Path(configured) if configured else store_dir() / "market_runs.db"


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(UTC)
    return value.isoformat()


@dataclass(frozen=True)
class FrozenUniverse:
    trade_date: str
    raw_symbols: tuple[str, ...]
    expected_symbols: tuple[str, ...]
    excluded_symbols: tuple[str, ...]
    content_digest: str
    source: str
    snapshot_meta: dict[str, object]
    approximate: bool
    captured_at: str

    def payload(self) -> dict[str, object]:
        return {
            "trade_date": self.trade_date,
            "raw_symbols": list(self.raw_symbols),
            "expected_symbols": list(self.expected_symbols),
            "excluded_symbols": list(self.excluded_symbols),
            "content_digest": self.content_digest,
            "source": self.source,
            "snapshot_meta": self.snapshot_meta,
            "approximate": self.approximate,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_payload(cls, value: dict[str, object]) -> "FrozenUniverse":
        return cls(
            trade_date=str(value["trade_date"]),
            raw_symbols=tuple(str(item) for item in value.get("raw_symbols", [])),
            expected_symbols=tuple(str(item) for item in value.get("expected_symbols", [])),
            excluded_symbols=tuple(str(item) for item in value.get("excluded_symbols", [])),
            content_digest=str(value["content_digest"]),
            source=str(value["source"]),
            snapshot_meta=dict(value.get("snapshot_meta") or {}),
            approximate=bool(value.get("approximate")),
            captured_at=str(value["captured_at"]),
        )


@dataclass(frozen=True)
class DailyRun:
    trade_date: str
    state: str
    universe: FrozenUniverse
    source_ready_at: str | None
    next_retry_at: str | None
    last_error: str | None
    completed_at: str | None
    updated_at: str


@dataclass(frozen=True)
class DailyRunSymbol:
    symbol: str
    status: str
    reason: str | None
    attempts: int
    source: str | None
    last_error: str | None
    evidence: dict[str, object] | None


class MarketRunStore:
    """Durable operational state for daily-market recovery; never a product source."""

    def __init__(self, path: Path | None = None):
        self.path = path or market_run_database_path()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _connect_readonly(self) -> sqlite3.Connection | None:
        """Open an existing ledger without creating a directory, file, or schema."""
        if not self.path.exists():
            return None
        conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM schema_metadata WHERE key='schema'").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_metadata(key,value) VALUES('schema',?)", (MARKET_RUN_SCHEMA,))
            elif str(row["value"]) != MARKET_RUN_SCHEMA:
                raise RuntimeError("market_run_schema_unsupported")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_runs("
                "trade_date TEXT PRIMARY KEY, state TEXT NOT NULL, universe_json TEXT NOT NULL, "
                "source_ready_at TEXT, next_retry_at TEXT, last_error TEXT, completed_at TEXT, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS daily_run_symbols("
                "trade_date TEXT NOT NULL, symbol TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, "
                "attempts INTEGER NOT NULL DEFAULT 0, source TEXT, last_error TEXT, evidence_json TEXT, updated_at TEXT NOT NULL, "
                "PRIMARY KEY(trade_date,symbol), FOREIGN KEY(trade_date) REFERENCES daily_runs(trade_date))"
            )
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(daily_run_symbols)").fetchall()}
            for column, definition in (
                ("attempts", "INTEGER NOT NULL DEFAULT 0"),
                ("source", "TEXT"),
                ("last_error", "TEXT"),
                ("evidence_json", "TEXT"),
            ):
                if column not in columns:
                    conn.execute(f"ALTER TABLE daily_run_symbols ADD COLUMN {column} {definition}")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_run_symbols_status ON daily_run_symbols(trade_date,status)")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS recovery_checkpoints("
                "singleton INTEGER PRIMARY KEY CHECK(singleton=1), last_complete_trade_date TEXT, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS task_leases("
                "name TEXT PRIMARY KEY, token TEXT NOT NULL, expires_at TEXT NOT NULL, heartbeat_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS lunch_runs("
                "trade_date TEXT PRIMARY KEY, state TEXT NOT NULL, plan_id TEXT, updated_at TEXT NOT NULL)"
            )

    def acquire_lease(self, *, name: str, now: datetime, lease_sec: int) -> str | None:
        self.initialize()
        token = uuid.uuid4().hex
        bounded_lease_sec = max(30, int(lease_sec))
        expires = now + timedelta(seconds=bounded_lease_sec)
        with self._transaction() as conn:
            row = conn.execute("SELECT token,expires_at,heartbeat_at FROM task_leases WHERE name=?", (name,)).fetchone()
            takeover_after = timedelta(seconds=max(30, min(90, bounded_lease_sec // 2)))
            heartbeat = datetime.fromisoformat(str(row["heartbeat_at"])) if row is not None else None
            if row is not None and datetime.fromisoformat(str(row["expires_at"])) > now and heartbeat is not None and heartbeat > now - takeover_after:
                return None
            conn.execute(
                "INSERT INTO task_leases(name,token,expires_at,heartbeat_at) VALUES(?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET token=excluded.token,expires_at=excluded.expires_at,heartbeat_at=excluded.heartbeat_at",
                (name, token, _iso(expires), _iso(now)),
            )
        return token

    def acquire_or_heartbeat_lease(self, *, name: str, token: str | None, now: datetime, lease_sec: int) -> str | None:
        """Keep a worker lease when owned, otherwise atomically acquire it."""
        if token and self.heartbeat_lease(name=name, token=token, now=now, lease_sec=lease_sec):
            return token
        return self.acquire_lease(name=name, now=now, lease_sec=lease_sec)

    def heartbeat_lease(self, *, name: str, token: str, now: datetime, lease_sec: int) -> bool:
        expires = now + timedelta(seconds=max(30, int(lease_sec)))
        with self._transaction() as conn:
            cursor = conn.execute(
                "UPDATE task_leases SET expires_at=?,heartbeat_at=? WHERE name=? AND token=?",
                (_iso(expires), _iso(now), name, token),
            )
            return cursor.rowcount == 1

    def ensure_run(self, *, universe: FrozenUniverse, now: datetime) -> DailyRun:
        self.initialize()
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM daily_runs WHERE trade_date=?", (universe.trade_date,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO daily_runs(trade_date,state,universe_json,updated_at) VALUES(?,?,?,?)",
                    (universe.trade_date, RUN_PENDING, json.dumps(universe.payload(), ensure_ascii=False, sort_keys=True), _iso(now)),
                )
                excluded = set(universe.excluded_symbols)
                conn.executemany(
                    "INSERT INTO daily_run_symbols(trade_date,symbol,status,reason,updated_at) VALUES(?,?,?,?,?)",
                    [
                        (universe.trade_date, symbol, "excluded" if symbol in excluded else "pending", "trusted_no_trade" if symbol in excluded else None, _iso(now))
                        for symbol in universe.raw_symbols
                    ],
                )
        return self.get_run(universe.trade_date)  # type: ignore[return-value]

    def get_run(self, trade_date: str) -> DailyRun | None:
        self.initialize()
        conn = self._connect()
        try:
            row = conn.execute("SELECT * FROM daily_runs WHERE trade_date=?", (trade_date,)).fetchone()
            return self._run_from_row(row) if row else None
        finally:
            conn.close()

    def replace_universe_before_fetch(self, *, universe: FrozenUniverse, now: datetime) -> DailyRun:
        """Persist final same-day suspension evidence before any bar request.

        A 14:57 denominator is frozen first.  Only a trustworthy post-close
        all-zero snapshot may narrow it, and never after fetching has begun.
        """
        self.initialize()
        with self._transaction() as conn:
            row = conn.execute("SELECT state,universe_json FROM daily_runs WHERE trade_date=?", (universe.trade_date,)).fetchone()
            if row is None:
                raise ValueError("daily_run_not_found")
            if str(row["state"]) in {RUN_PENDING, RUN_PROBING, RUN_RETRY_WAIT}:
                prior_universe = FrozenUniverse.from_payload(json.loads(str(row["universe_json"])))
                existing = {
                    str(item["symbol"]): {
                        "status": str(item["status"]),
                        "reason": str(item["reason"]) if item["reason"] else None,
                        "evidence_json": str(item["evidence_json"]) if item["evidence_json"] else None,
                    }
                    for item in conn.execute("SELECT symbol,status,reason,evidence_json FROM daily_run_symbols WHERE trade_date=?", (universe.trade_date,)).fetchall()
                }
                official_excluded = {
                    symbol
                    for symbol, item in existing.items()
                    if item["status"] == "excluded" and item["reason"] == "official_suspension"
                }
                excluded = set(universe.excluded_symbols) | official_excluded
                official_evidence = list(prior_universe.snapshot_meta.get("official_suspension_evidence") or [])
                snapshot_meta = dict(universe.snapshot_meta)
                if official_evidence:
                    snapshot_meta["official_suspension_evidence"] = official_evidence
                effective_universe = FrozenUniverse(
                    trade_date=universe.trade_date,
                    raw_symbols=universe.raw_symbols,
                    expected_symbols=tuple(symbol for symbol in universe.raw_symbols if symbol not in excluded),
                    excluded_symbols=tuple(sorted(excluded)),
                    content_digest=universe_digest(
                        trade_date=universe.trade_date,
                        raw_symbols=universe.raw_symbols,
                        expected_symbols=tuple(symbol for symbol in universe.raw_symbols if symbol not in excluded),
                        excluded_symbols=tuple(sorted(excluded)),
                    ),
                    source=universe.source,
                    snapshot_meta=snapshot_meta,
                    approximate=universe.approximate,
                    captured_at=universe.captured_at,
                )
                for symbol in universe.raw_symbols:
                    official = symbol in official_excluded
                    state = "excluded" if symbol in excluded else "pending"
                    reason = "official_suspension" if official else "trusted_no_trade" if symbol in excluded else None
                    if symbol in existing:
                        conn.execute(
                            "UPDATE daily_run_symbols SET status=?,reason=?,updated_at=? WHERE trade_date=? AND symbol=?",
                            (state, reason, _iso(now), universe.trade_date, symbol),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO daily_run_symbols(trade_date,symbol,status,reason,updated_at) VALUES(?,?,?,?,?)",
                            (universe.trade_date, symbol, state, reason, _iso(now)),
                        )
                conn.execute(
                    "UPDATE daily_runs SET universe_json=?,updated_at=? WHERE trade_date=?",
                    (json.dumps(effective_universe.payload(), ensure_ascii=False, sort_keys=True), _iso(now), universe.trade_date),
                )
        return self.get_run(universe.trade_date)  # type: ignore[return-value]

    def exclude_verified_suspensions(
        self,
        *,
        trade_date: str,
        evidence_by_symbol: dict[str, dict[str, object]],
        now: datetime,
    ) -> DailyRun:
        """Audit strict official no-bar facts without changing the raw universe.

        This path is intentionally available to reconstructed runs: official
        evidence is independent from an unavailable same-session spot snapshot.
        """
        self.initialize()
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM daily_runs WHERE trade_date=?", (trade_date,)).fetchone()
            if row is None:
                raise ValueError("daily_run_not_found")
            if str(row["state"]) == RUN_COMPLETE:
                return self._run_from_row(row)
            universe = FrozenUniverse.from_payload(json.loads(str(row["universe_json"])))
            raw = set(universe.raw_symbols)
            accepted = {
                str(symbol).zfill(6): dict(evidence)
                for symbol, evidence in evidence_by_symbol.items()
                if str(symbol).zfill(6) in raw
                and str(evidence.get("symbol") or "").zfill(6) == str(symbol).zfill(6)
                and str(evidence.get("trade_date") or "") == trade_date
                and str(evidence.get("state") or "") == "verified_suspended"
                and str(evidence.get("effective_suspension_date") or "") == trade_date
                and str(evidence.get("source") or "").startswith("cninfo+")
                and str(evidence.get("source_record_id") or "")
                and str(evidence.get("source_url") or "").startswith("https://")
                and str(evidence.get("published_at") or "")
                and str(evidence.get("content_digest") or "")
                and str(evidence.get("verification_basis") or "")
                and str(evidence.get("excerpt") or "")
            }
            if not accepted:
                return self._run_from_row(row)
            excluded = set(universe.excluded_symbols) | set(accepted)
            expected = tuple(symbol for symbol in universe.raw_symbols if symbol not in excluded)
            prior_evidence = [
                item for item in list(universe.snapshot_meta.get("official_suspension_evidence") or [])
                if isinstance(item, dict) and str(item.get("symbol") or "") not in accepted
            ]
            snapshot_meta = dict(universe.snapshot_meta)
            snapshot_meta["official_suspension_evidence"] = prior_evidence + [accepted[symbol] for symbol in sorted(accepted)]
            updated_universe = FrozenUniverse(
                trade_date=universe.trade_date,
                raw_symbols=universe.raw_symbols,
                expected_symbols=expected,
                excluded_symbols=tuple(sorted(excluded)),
                content_digest=universe_digest(
                    trade_date=universe.trade_date,
                    raw_symbols=universe.raw_symbols,
                    expected_symbols=expected,
                    excluded_symbols=tuple(sorted(excluded)),
                ),
                source=universe.source,
                snapshot_meta=snapshot_meta,
                approximate=universe.approximate,
                captured_at=universe.captured_at,
            )
            for symbol, evidence in accepted.items():
                conn.execute(
                    "UPDATE daily_run_symbols SET status='excluded',reason='official_suspension',source=?,last_error=NULL,evidence_json=?,updated_at=? "
                    "WHERE trade_date=? AND symbol=?",
                    (
                        str(evidence.get("source") or "cninfo+exchange"),
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                        _iso(now),
                        trade_date,
                        symbol,
                    ),
                )
            conn.execute(
                "UPDATE daily_runs SET universe_json=?,updated_at=? WHERE trade_date=?",
                (json.dumps(updated_universe.payload(), ensure_ascii=False, sort_keys=True), _iso(now), trade_date),
            )
        return self.get_run(trade_date)  # type: ignore[return-value]

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> DailyRun:
        return DailyRun(
            trade_date=str(row["trade_date"]),
            state=str(row["state"]),
            universe=FrozenUniverse.from_payload(json.loads(str(row["universe_json"]))),
            source_ready_at=str(row["source_ready_at"]) if row["source_ready_at"] else None,
            next_retry_at=str(row["next_retry_at"]) if row["next_retry_at"] else None,
            last_error=str(row["last_error"]) if row["last_error"] else None,
            completed_at=str(row["completed_at"]) if row["completed_at"] else None,
            updated_at=str(row["updated_at"]),
        )

    def set_source_ready(self, trade_date: str, now: datetime) -> None:
        self._set_run(trade_date, state=RUN_FETCHING, source_ready_at=_iso(now), next_retry_at=None, last_error=None, now=now)

    def record_retry(self, trade_date: str, *, now: datetime, retry_after_sec: int, error: str) -> None:
        self._set_run(
            trade_date,
            state=RUN_RETRY_WAIT,
            next_retry_at=_iso(now + timedelta(seconds=max(60, int(retry_after_sec)))),
            last_error=error,
            now=now,
        )

    def record_probe_wait(self, trade_date: str, *, now: datetime, retry_after_sec: int, error: str) -> None:
        self._set_run(
            trade_date,
            state=RUN_PROBING,
            next_retry_at=_iso(now + timedelta(seconds=max(60, int(retry_after_sec)))),
            last_error=error,
            now=now,
        )

    def complete(self, trade_date: str, now: datetime) -> None:
        self._set_run(trade_date, state=RUN_COMPLETE, completed_at=_iso(now), next_retry_at=None, last_error=None, now=now)
        with self._transaction() as conn:
            earlier_gap = conn.execute(
                "SELECT trade_date FROM daily_runs WHERE trade_date <= ? AND state != ? ORDER BY trade_date ASC LIMIT 1",
                (trade_date, RUN_COMPLETE),
            ).fetchone()
            checkpoint = trade_date if earlier_gap is None else None
            if checkpoint is None:
                existing = conn.execute("SELECT last_complete_trade_date FROM recovery_checkpoints WHERE singleton=1").fetchone()
                checkpoint = str(existing["last_complete_trade_date"]) if existing and existing["last_complete_trade_date"] else None
            conn.execute(
                "INSERT INTO recovery_checkpoints(singleton,last_complete_trade_date,updated_at) VALUES(1,?,?) "
                "ON CONFLICT(singleton) DO UPDATE SET last_complete_trade_date=excluded.last_complete_trade_date,updated_at=excluded.updated_at",
                (checkpoint, _iso(now)),
            )

    def _set_run(self, trade_date: str, *, state: str, now: datetime, source_ready_at: str | None | object = ..., next_retry_at: str | None | object = ..., last_error: str | None | object = ..., completed_at: str | None | object = ...) -> None:
        fields = ["state=?", "updated_at=?"]
        params: list[object] = [state, _iso(now)]
        for field, value in (("source_ready_at", source_ready_at), ("next_retry_at", next_retry_at), ("last_error", last_error), ("completed_at", completed_at)):
            if value is not ...:
                fields.append(f"{field}=?")
                params.append(value)
        params.append(trade_date)
        with self._transaction() as conn:
            conn.execute(f"UPDATE daily_runs SET {','.join(fields)} WHERE trade_date=?", params)

    def retry_due(self, run: DailyRun, now: datetime) -> bool:
        return run.next_retry_at is None or datetime.fromisoformat(run.next_retry_at) <= now

    def expected_symbols(self, trade_date: str) -> tuple[str, ...]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT symbol FROM daily_run_symbols WHERE trade_date=? AND status!='excluded' ORDER BY symbol", (trade_date,)).fetchall()
            return tuple(str(row["symbol"]) for row in rows)
        finally:
            conn.close()

    def update_coverage(
        self,
        *,
        trade_date: str,
        target_date: str,
        rows: dict[str, dict[str, object]],
        now: datetime,
        observed_symbols: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        expected = self.expected_symbols(trade_date)
        missing = tuple(symbol for symbol in expected if str(rows.get(symbol, {}).get("date") or "")[:10] != target_date)
        missing_set = set(missing)
        expected_set = set(expected)
        status_symbols = expected if observed_symbols is None else tuple(
            symbol for symbol in dict.fromkeys(observed_symbols) if symbol in expected_set
        )
        with self._transaction() as conn:
            conn.executemany(
                "UPDATE daily_run_symbols SET status=?,reason=?,last_error=?,updated_at=? WHERE trade_date=? AND symbol=?",
                [
                    ("pending" if symbol in missing_set else "fetched", "target_date_missing" if symbol in missing_set else None, None if symbol not in missing_set else "target_date_missing", _iso(now), trade_date, symbol)
                    for symbol in status_symbols
                ],
            )
        return missing

    def mark_attempt(self, *, trade_date: str, symbols: tuple[str, ...], now: datetime, source: str) -> None:
        if not symbols:
            return
        with self._transaction() as conn:
            conn.executemany(
                "UPDATE daily_run_symbols SET status='fetching',attempts=attempts+1,source=?,last_error=NULL,updated_at=? WHERE trade_date=? AND symbol=?",
                [(source, _iso(now), trade_date, symbol) for symbol in symbols],
            )

    def mark_attempt_failed(self, *, trade_date: str, symbols: tuple[str, ...], now: datetime, error: str = "target_date_missing") -> None:
        if not symbols:
            return
        with self._transaction() as conn:
            conn.executemany(
                "UPDATE daily_run_symbols SET status='failed',reason='target_date_missing',last_error=?,updated_at=? WHERE trade_date=? AND symbol=?",
                [(error, _iso(now), trade_date, symbol) for symbol in symbols],
            )

    def symbols(self, trade_date: str) -> tuple[DailyRunSymbol, ...]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT symbol,status,reason,attempts,source,last_error,evidence_json FROM daily_run_symbols WHERE trade_date=? ORDER BY symbol",
                (trade_date,),
            ).fetchall()
            return tuple(
                DailyRunSymbol(
                    symbol=str(row["symbol"]), status=str(row["status"]), reason=str(row["reason"]) if row["reason"] else None,
                    attempts=int(row["attempts"] or 0), source=str(row["source"]) if row["source"] else None,
                    last_error=str(row["last_error"]) if row["last_error"] else None,
                    evidence=json.loads(str(row["evidence_json"])) if row["evidence_json"] else None,
                )
                for row in rows
            )
        finally:
            conn.close()

    def last_complete_trade_date(self) -> str | None:
        self.initialize()
        conn = self._connect()
        try:
            row = conn.execute("SELECT last_complete_trade_date FROM recovery_checkpoints WHERE singleton=1").fetchone()
            return str(row["last_complete_trade_date"]) if row and row["last_complete_trade_date"] else None
        finally:
            conn.close()

    def mark_lunch(self, *, trade_date: str, state: str, plan_id: str | None, now: datetime) -> None:
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO lunch_runs(trade_date,state,plan_id,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(trade_date) DO UPDATE SET state=excluded.state,plan_id=excluded.plan_id,updated_at=excluded.updated_at",
                (trade_date, state, plan_id, _iso(now)),
            )

    def lunch_state(self, trade_date: str) -> str | None:
        self.initialize()
        conn = self._connect()
        try:
            row = conn.execute("SELECT state FROM lunch_runs WHERE trade_date=?", (trade_date,)).fetchone()
            return str(row["state"]) if row else None
        finally:
            conn.close()

    @staticmethod
    def _health_from_connection(conn: sqlite3.Connection) -> dict[str, object]:
        row = conn.execute("SELECT * FROM daily_runs WHERE state != ? ORDER BY trade_date ASC LIMIT 1", (RUN_COMPLETE,)).fetchone()
        if row is None:
            checkpoint = conn.execute("SELECT last_complete_trade_date FROM recovery_checkpoints WHERE singleton=1").fetchone()
            return {
                "state": "ready",
                "target_trade_date": str(checkpoint["last_complete_trade_date"]) if checkpoint and checkpoint["last_complete_trade_date"] else None,
                "completed": 0,
                "total": 0,
                "failed": 0,
                "next_retry_at": None,
                "approximate_universe": False,
            }
        run = MarketRunStore._run_from_row(row)
        counts = conn.execute(
            "SELECT COUNT(*) AS total, SUM(CASE WHEN status='fetched' OR status='excluded' THEN 1 ELSE 0 END) AS completed, SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed FROM daily_run_symbols WHERE trade_date=?",
            (run.trade_date,),
        ).fetchone()
        return {
            "state": run.state,
            "target_trade_date": run.trade_date,
            "completed": int(counts["completed"] or 0),
            "total": int(counts["total"] or 0),
            "failed": int(counts["failed"] or 0),
            "next_retry_at": run.next_retry_at,
            "approximate_universe": run.universe.approximate,
        }

    def health(self, *, initialize: bool = True) -> dict[str, object]:
        """Report recovery state; public readers set ``initialize=False`` to stay read-only."""
        if not initialize:
            conn = self._connect_readonly()
            if conn is None:
                return {"state": "not_started", "target_trade_date": None, "completed": 0, "total": 0, "failed": 0, "next_retry_at": None, "approximate_universe": False}
            try:
                return self._health_from_connection(conn)
            except sqlite3.OperationalError:
                return {"state": "unavailable", "target_trade_date": None, "completed": 0, "total": 0, "failed": 0, "next_retry_at": None, "approximate_universe": False}
            finally:
                conn.close()
        self.initialize()
        conn = self._connect()
        try:
            return self._health_from_connection(conn)
        finally:
            conn.close()


def universe_digest(*, trade_date: str, raw_symbols: tuple[str, ...], expected_symbols: tuple[str, ...], excluded_symbols: tuple[str, ...]) -> str:
    payload = {"schema": "daily_market_run_universe.v1", "trade_date": trade_date, "raw_symbols": list(raw_symbols), "expected_symbols": list(expected_symbols), "excluded_symbols": list(excluded_symbols)}
    return sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
