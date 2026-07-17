from __future__ import annotations

"""The sole product-facing persistence boundary for GP.

Reads never initialize SQLite, change journaling, or acquire a write
transaction.  Bootstrap/migration is explicit at a process or write boundary.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator

from .contracts.objects import DayBook, LiveSlotArtifact, MarketBook
from .core.paths import store_dir
from .runtime.market_time import iso_day
from .runtime.utils import gen_id, now_iso


SCHEMA_VERSION = 3
SNAPSHOT_SCHEMA = "RecommendationSnapshot.v1"
WRITE_WAIT_MS = 1200
READ_WAIT_MS = 2000
_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAPPED: set[str] = set()


class AgentStoreError(RuntimeError):
    pass


class StorageBusyError(AgentStoreError):
    def __init__(self, retry_after_ms: int = WRITE_WAIT_MS):
        super().__init__("storage_busy")
        self.retry_after_ms = retry_after_ms


class SnapshotIntegrityError(AgentStoreError):
    pass


class MigrationError(AgentStoreError):
    pass


class SessionSnapshotConflict(AgentStoreError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _migration_checksum(version: int) -> str:
    if version == 1:
        return _hash({"schema": 1, "snapshot_schema": SNAPSHOT_SCHEMA})
    if version == 2:
        return _hash({"schema": 2, "snapshot_schema": SNAPSHOT_SCHEMA, "market_time": True, "daybooks": True})
    if version == 3:
        return _hash(
            {
                "schema": 3,
                "snapshot_schema": SNAPSHOT_SCHEMA,
                "calendar_blocking_reason": True,
            }
        )
    raise ValueError(f"unknown_agent_migration:{version}")


def agent_db_path() -> Path:
    path = Path(os.getenv("GP_AGENT_DB") or str(store_dir() / "agent.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class StoredSnapshot:
    snapshot_id: str
    schema_version: str
    as_of: str  # Deprecated compatibility alias for observed_at.
    decision: str
    tradeable: bool
    payload: dict[str, Any]
    payload_hash: str
    created_at: str
    decision_trade_day: str | None = None
    daybook_effective_day: str | None = None
    pulse_trade_day: str | None = None
    pulse_slot_closed_at: str | None = None
    observed_at: str | None = None
    market_phase: str | None = None
    target_mode: str | None = None
    pending_eod_day: str | None = None
    calendar_blocking_reason: str | None = None


class AgentStore:
    def __init__(self, path: Path | None = None):
        self.path = path or agent_db_path()

    @property
    def _key(self) -> str:
        return str(self.path.resolve())

    def _connect_write(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=WRITE_WAIT_MS / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={WRITE_WAIT_MS}")
        return conn

    def _connect_read(self) -> sqlite3.Connection | None:
        if not self.path.exists():
            return None
        conn = sqlite3.connect(
            f"{self.path.resolve().as_uri()}?mode=ro",
            uri=True,
            timeout=READ_WAIT_MS / 1000,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute(f"PRAGMA busy_timeout={READ_WAIT_MS}")
        return conn

    @staticmethod
    def _is_busy(exc: BaseException) -> bool:
        return isinstance(exc, sqlite3.OperationalError) and ("locked" in str(exc).lower() or "busy" in str(exc).lower())

    def initialize(self) -> None:
        """Apply additive migrations once per process/path, outside read requests."""
        if self._key in _BOOTSTRAPPED:
            return
        with _BOOTSTRAP_LOCK:
            if self._key in _BOOTSTRAPPED:
                return
            conn = self._connect_write()
            try:
                conn.execute("PRAGMA journal_mode=DELETE")
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, checksum TEXT NOT NULL)")
                rows = conn.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall()
                found = {int(row["version"]): str(row["checksum"]) for row in rows}
                if any(version not in {1, 2, 3} for version in found) or any(found[v] != _migration_checksum(v) for v in found):
                    raise MigrationError("agent_db_schema_mismatch")
                if 1 not in found:
                    for statement in (
                        "CREATE TABLE IF NOT EXISTS recommendation_snapshots(snapshot_id TEXT PRIMARY KEY,schema_version TEXT NOT NULL,as_of TEXT NOT NULL,decision TEXT NOT NULL,tradeable INTEGER NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)",
                        "CREATE TABLE IF NOT EXISTS current_snapshot(singleton INTEGER PRIMARY KEY CHECK(singleton=1),snapshot_id TEXT NOT NULL REFERENCES recommendation_snapshots(snapshot_id))",
                        "CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY,active_snapshot_id TEXT NOT NULL REFERENCES recommendation_snapshots(snapshot_id),created_at TEXT NOT NULL,updated_at TEXT NOT NULL)",
                        "CREATE TABLE IF NOT EXISTS turns(turn_id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,seq INTEGER NOT NULL,client_turn_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('user','assistant')),content TEXT NOT NULL,snapshot_id TEXT NOT NULL REFERENCES recommendation_snapshots(snapshot_id),payload_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(session_id,seq),UNIQUE(session_id,client_turn_id,role))",
                        "CREATE TABLE IF NOT EXISTS claims(claim_id TEXT PRIMARY KEY,turn_id TEXT NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE,payload_json TEXT NOT NULL,created_at TEXT NOT NULL)",
                    ):
                        conn.execute(statement)
                    conn.execute("INSERT INTO schema_migrations(version,applied_at,checksum) VALUES(?,?,?)", (1, now_iso(), _migration_checksum(1)))
                if 2 not in found:
                    cols = {row["name"] for row in conn.execute("PRAGMA table_info(recommendation_snapshots)").fetchall()}
                    for name in ("decision_trade_day", "daybook_effective_day", "pulse_trade_day", "pulse_slot_closed_at", "observed_at", "market_phase", "target_mode", "pending_eod_day"):
                        if name not in cols:
                            conn.execute(f"ALTER TABLE recommendation_snapshots ADD COLUMN {name} TEXT")
                    session_cols = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
                    if "next_seq" not in session_cols:
                        conn.execute("ALTER TABLE sessions ADD COLUMN next_seq INTEGER NOT NULL DEFAULT 1")
                    conn.execute(
                        """
                        UPDATE sessions
                        SET next_seq=MAX(
                            next_seq,
                            COALESCE(
                                (SELECT MAX(t.seq)+1 FROM turns t WHERE t.session_id=sessions.session_id),
                                1
                            )
                        )
                        """
                    )
                    conn.execute("CREATE TABLE IF NOT EXISTS daybook_versions(daybook_id TEXT PRIMARY KEY,daybook_trading_day TEXT NOT NULL,producer_hash TEXT NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)")
                    conn.execute("CREATE INDEX IF NOT EXISTS idx_daybook_versions_lookup ON daybook_versions(daybook_trading_day,producer_hash,created_at DESC)")
                    conn.execute("INSERT INTO schema_migrations(version,applied_at,checksum) VALUES(?,?,?)", (2, now_iso(), _migration_checksum(2)))
                if 3 not in found:
                    cols = {
                        row["name"]
                        for row in conn.execute(
                            "PRAGMA table_info(recommendation_snapshots)"
                        ).fetchall()
                    }
                    if "calendar_blocking_reason" not in cols:
                        conn.execute(
                            "ALTER TABLE recommendation_snapshots "
                            "ADD COLUMN calendar_blocking_reason TEXT"
                        )
                    conn.execute(
                        "INSERT INTO schema_migrations(version,applied_at,checksum) VALUES(?,?,?)",
                        (3, now_iso(), _migration_checksum(3)),
                    )
                conn.execute("COMMIT")
                _BOOTSTRAPPED.add(self._key)
            except BaseException as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                if self._is_busy(exc):
                    raise StorageBusyError() from exc
                raise
            finally:
                conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        conn = self._connect_write()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            if self._is_busy(exc):
                raise StorageBusyError() from exc
            raise
        finally:
            conn.close()

    def save_daybook(self, daybook: DayBook) -> str:
        with self._transaction() as conn:
            return self._insert_daybook(conn, daybook)

    @staticmethod
    def _insert_daybook(conn: sqlite3.Connection, daybook: DayBook) -> str:
        payload = daybook.model_dump(mode="json")
        payload_hash = _hash(payload)
        daybook_id = f"daybook_{payload_hash[:24]}"
        existing = conn.execute(
            "SELECT payload_hash FROM daybook_versions WHERE daybook_id=?",
            (daybook_id,),
        ).fetchone()
        if existing is not None and str(existing["payload_hash"]) != payload_hash:
            raise SnapshotIntegrityError("daybook_immutable_conflict")
        conn.execute(
            "INSERT OR IGNORE INTO daybook_versions(daybook_id,daybook_trading_day,producer_hash,payload_json,payload_hash,created_at) VALUES(?,?,?,?,?,?)",
            (daybook_id, iso_day(daybook.trading_day), _hash(daybook.producer), _canonical_json(payload), payload_hash, now_iso()),
        )
        return daybook_id

    def load_daybook(self, effective_day: str, *, producer: dict[str, str] | None = None) -> DayBook | None:
        conn = self._connect_read()
        if conn is None:
            return None
        try:
            params: list[Any] = [iso_day(effective_day)]
            sql = "SELECT payload_json FROM daybook_versions WHERE daybook_trading_day=?"
            if producer is not None:
                sql += " AND producer_hash=?"
                params.append(_hash(producer))
            sql += " ORDER BY created_at DESC LIMIT 1"
            row = conn.execute(sql, params).fetchone()
            return DayBook.model_validate(json.loads(row["payload_json"])) if row else None
        except sqlite3.OperationalError as exc:
            if self._is_busy(exc):
                raise StorageBusyError(READ_WAIT_MS) from exc
            raise
        finally:
            conn.close()

    @staticmethod
    def _record_for_book(
        book: MarketBook, *, market_time: Any | None = None
    ) -> StoredSnapshot:
        payload = {"book": book.model_dump(mode="json")}
        decision = "recommend" if bool(book.daybook.picks) else "no_trade"
        snapshot_id = str(book.artifact_id or book.book_version)
        observed_at = str(getattr(market_time, "observed_at", None) or book.updated_at or "")
        if not snapshot_id or not observed_at:
            raise SnapshotIntegrityError("snapshot_identity_or_observed_at_missing")
        record = StoredSnapshot(
            snapshot_id=snapshot_id, schema_version=SNAPSHOT_SCHEMA, as_of=observed_at, decision=decision,
            tradeable=bool(book.publish_allowed and book.daybook.tradeable), payload=payload, payload_hash=_hash(payload), created_at=now_iso(),
            decision_trade_day=iso_day(getattr(market_time, "decision_trade_day", None) or book.trading_day),
            daybook_effective_day=iso_day(getattr(market_time, "daybook_effective_day", None) or book.daybook_effective_day or book.daybook.trading_day),
            pulse_trade_day=iso_day(getattr(market_time, "pulse_trade_day", None) or book.pulse_trade_day),
            pulse_slot_closed_at=getattr(market_time, "pulse_slot_closed_at", None) or book.pulse_slot_at,
            observed_at=observed_at,
            market_phase=getattr(market_time, "market_phase", None) or book.market_phase,
            target_mode=getattr(market_time, "target_mode", None),
            pending_eod_day=iso_day(getattr(market_time, "pending_eod_day", None)),
            calendar_blocking_reason=getattr(
                market_time, "calendar_blocking_reason", None
            ),
        )
        return record

    def publish_book(self, book: MarketBook, *, market_time: Any | None = None) -> StoredSnapshot:
        record = self._record_for_book(book, market_time=market_time)
        self.publish_snapshot(record)
        return record

    def publish_runtime_artifact(self, daybook: DayBook, artifact: LiveSlotArtifact, *, market_time: Any | None = None) -> StoredSnapshot:
        if iso_day(artifact.daybook_effective_day) != iso_day(daybook.trading_day):
            raise SnapshotIntegrityError("snapshot_trade_day_mismatch")
        allowed = {pick.symbol for pick in [*daybook.picks, *daybook.reserve_picks]}
        if any(entry.symbol not in allowed for entry in artifact.board) or {entry.symbol for entry in artifact.board} != {pick.symbol for pick in daybook.picks}:
            raise SnapshotIntegrityError("snapshot_board_daybook_mismatch")
        deferred = dict(
            (daybook.source_meta or {}).get("_deferred_persistence") or {}
        )
        existing_binding = dict(
            (daybook.source_meta or {}).get("runtime_evidence_binding") or {}
        )
        if not deferred:
            if not existing_binding:
                raise SnapshotIntegrityError("runtime_deferred_evidence_missing")
            deferred = self._load_bound_runtime_evidence(existing_binding)
        published_daybook = daybook.model_copy(deep=True)
        published_daybook.source_meta.pop("_deferred_persistence", None)
        decision_snapshot, reference, evidence_binding = self._validate_runtime_evidence(
            published_daybook,
            artifact,
            deferred,
            market_time=market_time,
        )
        if existing_binding and existing_binding != evidence_binding:
            raise SnapshotIntegrityError("runtime_evidence_binding_mismatch")
        published_daybook.source_meta["runtime_evidence_binding"] = evidence_binding
        book = MarketBook(
            trading_day=artifact.trade_day, book_version=artifact.artifact_id, updated_at=artifact.updated_at, regime=daybook.regime,
            daybook=published_daybook, board=artifact.board, watchset=list(artifact.tracked_universe.total), symbol_states=artifact.symbol_states,
            portfolio_snapshot={}, last_closed_5m=artifact.slot_at, side_results=[], artifact_id=artifact.artifact_id, slot_id=artifact.slot_id,
            slot_status=artifact.slot_status, publish_allowed=artifact.publish_allowed, daybook_effective_day=artifact.daybook_effective_day,
            pulse_trade_day=artifact.trade_day if artifact.slot_at else None, pulse_slot_at=artifact.slot_at, market_phase=artifact.market_phase,
            data_status=str((artifact.provider_meta or {}).get("data_status") or "daily_plan"), gate=artifact.gate, data_quality=artifact.data_quality,
            tracked_universe=artifact.tracked_universe, producer={"schema_version": SNAPSHOT_SCHEMA, "selection_policy": str((artifact.producer or {}).get("selection_policy") or "adaptive_policy_single_path")},
        )
        record = self._record_for_book(book, market_time=market_time)
        self._validate_snapshot(record)

        saved_decision_id = self._persist_decision_snapshot(decision_snapshot)
        if saved_decision_id != evidence_binding["decision_context_snapshot_id"]:
            raise SnapshotIntegrityError("runtime_decision_snapshot_persistence_mismatch")
        if reference is not None:
            saved_reference_id, saved_pending_id = self._persist_serenity_reference(
                reference,
                decision_day=str(deferred.get("decision_day") or ""),
                epoch=int(deferred.get("epoch") or 0),
                formula_version=str(deferred.get("formula_version") or ""),
            )
            if (
                saved_reference_id
                != evidence_binding["serenity_reference_snapshot_id"]
                or saved_pending_id != evidence_binding["serenity_pending_id"]
            ):
                raise SnapshotIntegrityError("runtime_serenity_persistence_mismatch")

        # Cross-database evidence is written first.  The product-facing pointer
        # is advanced only inside this final agent.db transaction, so a failure
        # cannot expose a snapshot whose evidence bundle is incomplete.
        with self._transaction() as conn:
            self._insert_daybook(conn, published_daybook)
            self._insert_snapshot(conn, record)
            self._advance_current_snapshot(conn, record.snapshot_id)
        return record

    @staticmethod
    def _validate_runtime_evidence(
        daybook: DayBook,
        artifact: LiveSlotArtifact,
        deferred: dict[str, Any],
        *,
        market_time: Any | None,
    ) -> tuple[dict[str, Any], Any | None, dict[str, Any]]:
        from .decision_engine.serenity_policy import (
            freeze_risk_plan,
            reference_input_checksum,
            reference_learning_sample_id,
        )
        from .serenity.models import NATIVE_SERENITY_FORMULA_VERSION, SerenityReferenceSnapshot
        from .serenity.store import pending_evaluation_id

        meta = dict(daybook.source_meta or {})
        decision_snapshot = dict(deferred.get("decision_snapshot") or {})
        if not decision_snapshot:
            raise SnapshotIntegrityError("runtime_deferred_decision_snapshot_missing")
        decision_context_snapshot_id = str(
            meta.get("decision_context_snapshot_id") or ""
        )
        if (
            str(decision_snapshot.get("schema") or "")
            != "DecisionContextSnapshot.v1"
            or not decision_context_snapshot_id
            or str(decision_snapshot.get("snapshot_id") or "")
            != decision_context_snapshot_id
        ):
            raise SnapshotIntegrityError("runtime_decision_snapshot_identity_mismatch")

        selected_symbols = [pick.symbol for pick in daybook.picks]
        expected_decision = "recommend" if selected_symbols else "no_trade"
        if (
            str(meta.get("decision") or "") != expected_decision
            or str(decision_snapshot.get("final_decision") or "")
            != expected_decision
            or [str(item) for item in list(decision_snapshot.get("selected_symbols") or [])]
            != selected_symbols
        ):
            raise SnapshotIntegrityError("runtime_decision_snapshot_result_mismatch")
        attestation = dict(meta.get("serenity_native_attestation") or {})
        decision_attestation = dict(
            decision_snapshot.get("serenity_native_attestation") or {}
        )
        if (
            dict(decision_snapshot.get("serenity_candidate_target") or {})
            != dict(meta.get("serenity_candidate_target") or {})
            or decision_attestation != attestation
            or str(decision_snapshot.get("serenity_source_run_id") or "")
            != str(meta.get("serenity_source_run_id") or "")
            or str(decision_snapshot.get("serenity_readiness_revision") or "")
            != str(meta.get("serenity_readiness_revision") or "")
            or str(decision_snapshot.get("serenity_semantic_revision") or "")
            != str(meta.get("serenity_semantic_revision") or "")
            or str(decision_snapshot.get("serenity_poll_finished_at") or "")
            != str(meta.get("serenity_poll_finished_at") or "")
            or str(decision_snapshot.get("serenity_poll_expires_at") or "")
            != str(meta.get("serenity_poll_expires_at") or "")
            or (
                attestation
                and [
                    str(item)
                    for item in list(
                        dict(decision_snapshot.get("ranking_output") or {}).get(
                            "ranked_symbols"
                        )
                        or []
                    )
                ]
                != [
                    str(item)
                    for item in list(attestation.get("ranked_symbols") or [])
                ]
            )
        ):
            raise SnapshotIntegrityError("runtime_decision_snapshot_evidence_mismatch")

        expected_decision_day = iso_day(
            getattr(market_time, "decision_trade_day", None)
            or decision_snapshot.get("decision_trade_day")
            or artifact.trade_day
        )
        expected_daybook_day = iso_day(
            getattr(market_time, "daybook_effective_day", None)
            or artifact.daybook_effective_day
            or daybook.trading_day
        )
        decision_observed_at = str(decision_snapshot.get("observed_at") or "")
        daybook_market_time = dict(meta.get("market_time") or {})
        if (
            not expected_decision_day
            or not expected_daybook_day
            or not decision_observed_at
            or iso_day(decision_snapshot.get("decision_trade_day"))
            != expected_decision_day
            or iso_day(decision_snapshot.get("daybook_effective_day"))
            != expected_daybook_day
            or iso_day(decision_snapshot.get("as_of")) != expected_daybook_day
            or iso_day(daybook.trading_day) != expected_daybook_day
            or (
                daybook_market_time.get("observed_at")
                and str(daybook_market_time.get("observed_at"))
                != decision_observed_at
            )
        ):
            raise SnapshotIntegrityError("runtime_decision_snapshot_time_mismatch")

        formula_version = str(meta.get("serenity_formula_version") or "")
        semantic_revision = str(meta.get("serenity_semantic_revision") or "")
        policy = dict(meta.get("serenity_policy_snapshot") or {})
        try:
            policy_epoch = int(policy.get("epoch"))
            deferred_epoch = int(deferred.get("epoch"))
        except (TypeError, ValueError) as exc:
            raise SnapshotIntegrityError("runtime_serenity_policy_binding_invalid") from exc
        if (
            not formula_version
            or formula_version != NATIVE_SERENITY_FORMULA_VERSION
            or (
                meta.get("serenity_native_ready") is True
                and not semantic_revision
            )
            or str(policy.get("formula_version") or "") != formula_version
            or str(deferred.get("formula_version") or "") != formula_version
            or str(decision_snapshot.get("serenity_formula_version") or "")
            != formula_version
            or dict(decision_snapshot.get("serenity_policy_snapshot") or {})
            != policy
            or policy_epoch < 1
            or deferred_epoch != policy_epoch
            or iso_day(deferred.get("decision_day")) != expected_decision_day
        ):
            raise SnapshotIntegrityError("runtime_serenity_policy_binding_invalid")

        source_reference_id = str(
            meta.get("serenity_reference_snapshot_id") or ""
        )
        decision_reference_id = str(
            decision_snapshot.get("serenity_reference_snapshot_id") or ""
        )
        reference_payload = deferred.get("serenity_reference_snapshot")
        reference = None
        pending_id = None
        reference_checksum = None
        if reference_payload:
            try:
                reference = SerenityReferenceSnapshot.model_validate(reference_payload)
            except Exception as exc:  # noqa: BLE001
                raise SnapshotIntegrityError("runtime_serenity_reference_invalid") from exc
            if (
                expected_decision != "recommend"
                or reference.snapshot_id != source_reference_id
                or reference.snapshot_id != decision_reference_id
                or str(reference.decision_context_snapshot_id or "")
                != decision_context_snapshot_id
                or iso_day(reference.decision_day) != expected_decision_day
                or str(reference.decision_at) != decision_observed_at
            ):
                raise SnapshotIntegrityError("runtime_serenity_reference_binding_mismatch")
            attested_candidates = {
                str(symbol): dict(item or {})
                for symbol, item in dict(attestation.get("candidates") or {}).items()
            }
            if (
                set(reference.signals) != set(attested_candidates)
                or set(reference.target_symbols) != set(attested_candidates)
                or reference.policy_state != str(policy.get("state") or "")
                or float(reference.actual_weight)
                != float(policy.get("applied_weight") or 0.0)
                or reference.baseline_selected_symbols
                != list(policy.get("baseline_selected_symbols") or [])
                or reference.applied_selected_symbols
                != list(policy.get("applied_selected_symbols") or [])
                or reference.would_change_topk
                != bool(policy.get("would_change_topk"))
                or [
                    item.model_dump(mode="json")
                    for item in reference.counterfactual_arms
                ]
                != list(decision_snapshot.get("serenity_counterfactuals") or [])
                or [
                    item.model_dump(mode="json")
                    for item in reference.reference_counterfactual_arms
                ]
                != list(
                    decision_snapshot.get("serenity_reference_counterfactuals")
                    or []
                )
            ):
                raise SnapshotIntegrityError("runtime_serenity_reference_binding_mismatch")
            for symbol, signal in reference.signals.items():
                record = attested_candidates[symbol]
                if (
                    signal.status != str(record.get("status") or "")
                    or signal.input_hash != str(record.get("input_hash") or "")
                    or signal.decision_at != str(record.get("decision_at") or "")
                    or str(signal.target_id or "")
                    != str(record.get("target_id") or "")
                    or str(signal.source_run_id or "")
                    != str(record.get("source_run_id") or "")
                    or signal.fact_ids != list(record.get("fact_ids") or [])
                    or signal.learning_eligible
                    != bool(record.get("learning_eligible"))
                    or float(signal.alpha_value)
                    != float(record.get("alpha_value") or 0.0)
                    or signal.lineage != dict(record.get("lineage") or {})
                    or [fact.model_dump(mode="json") for fact in signal.facts]
                    != list(record.get("facts") or [])
                ):
                    raise SnapshotIntegrityError(
                        "runtime_serenity_reference_signal_mismatch"
                    )
            recomputed_sample_id = reference_learning_sample_id(
                decision_day=reference.decision_day,
                signals=reference.signals,
                arms=reference.counterfactual_arms,
                risk_plans=reference.risk_plans,
            )
            recomputed_checksum = reference_input_checksum(
                decision_context_snapshot_id=reference.decision_context_snapshot_id,
                decision_day=reference.decision_day,
                decision_at=reference.decision_at,
                signals=reference.signals,
                arms=reference.counterfactual_arms,
                reference_arms=reference.reference_counterfactual_arms,
                risk_plans=reference.risk_plans,
                learning_sample_id=reference.learning_sample_id,
                actual_weight=reference.actual_weight,
                policy_state=reference.policy_state,
                baseline_selected_symbols=reference.baseline_selected_symbols,
                applied_selected_symbols=reference.applied_selected_symbols,
                would_change_topk=reference.would_change_topk,
            )
            decision_risk = dict(
                decision_snapshot.get("serenity_outcome_risk_plans") or {}
            )
            if (
                recomputed_sample_id != reference.learning_sample_id
                or recomputed_checksum != reference.input_checksum
                or reference.snapshot_id
                != "sersnap_" + reference.input_checksum[:24]
                or any(
                    freeze_risk_plan(decision_risk.get(symbol)) != dict(plan)
                    for symbol, plan in reference.risk_plans.items()
                )
            ):
                raise SnapshotIntegrityError("runtime_serenity_reference_checksum_mismatch")
            pending_id = pending_evaluation_id(
                reference_snapshot_id=reference.snapshot_id,
                decision_context_snapshot_id=decision_context_snapshot_id,
                epoch=policy_epoch,
                formula_version=formula_version,
            )
            reference_checksum = reference.input_checksum
        elif source_reference_id or decision_reference_id or expected_decision == "recommend":
            raise SnapshotIntegrityError("runtime_serenity_reference_missing")

        binding = {
            "schema": "RuntimeEvidenceBinding.v1",
            "decision_context_snapshot_id": decision_context_snapshot_id,
            "decision_snapshot_payload_hash": _hash(decision_snapshot),
            "serenity_reference_snapshot_id": (
                reference.snapshot_id if reference is not None else None
            ),
            "serenity_reference_input_checksum": reference_checksum,
            "serenity_pending_id": pending_id,
            "formula_version": formula_version,
            "policy_epoch": policy_epoch,
            "decision_trade_day": expected_decision_day,
            "daybook_effective_day": expected_daybook_day,
            "decision_observed_at": decision_observed_at,
        }
        return decision_snapshot, reference, binding

    @staticmethod
    def _load_bound_runtime_evidence(
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        from .market_memory.store import load_decision_snapshot
        from .serenity.store import (
            load_pending_evaluation,
            load_reference_snapshot,
        )

        if str(binding.get("schema") or "") != "RuntimeEvidenceBinding.v1":
            raise SnapshotIntegrityError("runtime_evidence_binding_invalid")
        decision_context_snapshot_id = str(
            binding.get("decision_context_snapshot_id") or ""
        )
        decision_snapshot = load_decision_snapshot(decision_context_snapshot_id)
        if (
            not decision_snapshot
            or _hash(decision_snapshot)
            != str(binding.get("decision_snapshot_payload_hash") or "")
        ):
            raise SnapshotIntegrityError("runtime_bound_decision_snapshot_unavailable")
        reference_id = str(
            binding.get("serenity_reference_snapshot_id") or ""
        )
        pending_id = str(binding.get("serenity_pending_id") or "")
        reference_payload = None
        if reference_id:
            reference = load_reference_snapshot(reference_id)
            pending = load_pending_evaluation(pending_id)
            if (
                reference is None
                or pending is None
                or reference.input_checksum
                != str(binding.get("serenity_reference_input_checksum") or "")
                or str(pending.get("reference_snapshot_id") or "")
                != reference_id
                or str(pending.get("decision_context_snapshot_id") or "")
                != decision_context_snapshot_id
                or iso_day(pending.get("decision_day"))
                != iso_day(binding.get("decision_trade_day"))
                or int(pending.get("epoch") or 0)
                != int(binding.get("policy_epoch") or 0)
                or str(pending.get("formula_version") or "")
                != str(binding.get("formula_version") or "")
                or str(pending.get("input_hash") or "")
                != reference.input_checksum
            ):
                raise SnapshotIntegrityError("runtime_bound_serenity_evidence_unavailable")
            reference_payload = reference.model_dump(mode="json")
        elif (
            pending_id
            or binding.get("serenity_reference_input_checksum") is not None
        ):
            raise SnapshotIntegrityError("runtime_evidence_binding_invalid")
        return {
            "decision_snapshot": decision_snapshot,
            "serenity_reference_snapshot": reference_payload,
            "decision_day": str(binding.get("decision_trade_day") or ""),
            "epoch": int(binding.get("policy_epoch") or 0),
            "formula_version": str(binding.get("formula_version") or ""),
        }

    @staticmethod
    def _persist_decision_snapshot(snapshot: dict[str, Any]) -> str:
        from .market_memory.store import save_decision_snapshot

        return save_decision_snapshot(snapshot)

    @staticmethod
    def _persist_serenity_reference(
        reference: Any,
        *,
        decision_day: str,
        epoch: int,
        formula_version: str,
    ) -> tuple[str, str]:
        from .serenity.store import save_reference_and_enqueue_pending

        return save_reference_and_enqueue_pending(
            reference,
            decision_day=decision_day,
            epoch=epoch,
            formula_version=formula_version,
        )

    def _validate_snapshot(self, snapshot: StoredSnapshot) -> MarketBook:
        if snapshot.schema_version != SNAPSHOT_SCHEMA or snapshot.decision not in {"recommend", "no_trade"} or snapshot.payload_hash != _hash(snapshot.payload):
            raise SnapshotIntegrityError("snapshot_invalid")
        try:
            book = MarketBook.model_validate(snapshot.payload.get("book"))
        except Exception as exc:  # noqa: BLE001
            raise SnapshotIntegrityError("snapshot_book_invalid") from exc
        if str(book.artifact_id or book.book_version) != snapshot.snapshot_id:
            raise SnapshotIntegrityError("snapshot_identity_mismatch")
        if bool(book.daybook.picks) != (snapshot.decision == "recommend"):
            raise SnapshotIntegrityError("snapshot_decision_payload_mismatch")
        source_meta = dict(book.daybook.source_meta or {})
        from .runtime.native_snapshot import (
            native_snapshot_integrity_errors,
            pending_native_snapshot_integrity_errors,
        )

        integrity_errors = (
            native_snapshot_integrity_errors(snapshot, book)
            if source_meta.get("serenity_native_ready") is True
            or bool(book.daybook.picks)
            else pending_native_snapshot_integrity_errors(snapshot, book)
        )
        if integrity_errors:
            raise SnapshotIntegrityError(integrity_errors[0])
        return book

    @staticmethod
    def _insert_snapshot(conn: sqlite3.Connection, snapshot: StoredSnapshot) -> None:
        columns = "snapshot_id,schema_version,as_of,decision,tradeable,payload_json,payload_hash,created_at,decision_trade_day,daybook_effective_day,pulse_trade_day,pulse_slot_closed_at,observed_at,market_phase,target_mode,pending_eod_day,calendar_blocking_reason"
        values = (snapshot.snapshot_id, snapshot.schema_version, snapshot.as_of, snapshot.decision, int(snapshot.tradeable), _canonical_json(snapshot.payload), snapshot.payload_hash, snapshot.created_at, snapshot.decision_trade_day, snapshot.daybook_effective_day, snapshot.pulse_trade_day, snapshot.pulse_slot_closed_at, snapshot.observed_at, snapshot.market_phase, snapshot.target_mode, snapshot.pending_eod_day, snapshot.calendar_blocking_reason)
        row = conn.execute("SELECT payload_hash FROM recommendation_snapshots WHERE snapshot_id=?", (snapshot.snapshot_id,)).fetchone()
        if row is not None and row["payload_hash"] != snapshot.payload_hash:
            raise SnapshotIntegrityError("snapshot_immutable_conflict")
        if row is None:
            conn.execute(f"INSERT INTO recommendation_snapshots({columns}) VALUES({','.join('?' for _ in values)})", values)

    @staticmethod
    def _advance_current_snapshot(conn: sqlite3.Connection, snapshot_id: str) -> None:
        conn.execute("INSERT INTO current_snapshot(singleton,snapshot_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET snapshot_id=excluded.snapshot_id", (snapshot_id,))

    def publish_snapshot(self, snapshot: StoredSnapshot) -> None:
        self._validate_snapshot(snapshot)
        with self._transaction() as conn:
            self._insert_snapshot(conn, snapshot)
            self._advance_current_snapshot(conn, snapshot.snapshot_id)

    def _decode_snapshot(self, row: sqlite3.Row) -> StoredSnapshot:
        payload = json.loads(row["payload_json"])
        if row["schema_version"] != SNAPSHOT_SCHEMA or _hash(payload) != row["payload_hash"]:
            raise SnapshotIntegrityError("snapshot_corrupt")
        keys = set(row.keys())
        return StoredSnapshot(snapshot_id=row["snapshot_id"], schema_version=row["schema_version"], as_of=row["as_of"], decision=row["decision"], tradeable=bool(row["tradeable"]), payload=payload, payload_hash=row["payload_hash"], created_at=row["created_at"], **{name: row[name] if name in keys else None for name in ("decision_trade_day", "daybook_effective_day", "pulse_trade_day", "pulse_slot_closed_at", "observed_at", "market_phase", "target_mode", "pending_eod_day", "calendar_blocking_reason")})

    def _read_snapshot(self, sql: str, params: tuple[Any, ...] = ()) -> StoredSnapshot | None:
        conn = self._connect_read()
        if conn is None:
            return None
        try:
            row = conn.execute(sql, params).fetchone()
            return self._decode_snapshot(row) if row else None
        except sqlite3.OperationalError as exc:
            if self._is_busy(exc):
                raise StorageBusyError(READ_WAIT_MS) from exc
            raise
        finally:
            conn.close()

    def current_snapshot(self) -> StoredSnapshot | None:
        return self._read_snapshot("SELECT s.* FROM current_snapshot c JOIN recommendation_snapshots s ON s.snapshot_id=c.snapshot_id WHERE c.singleton=1")

    def load_snapshot(self, snapshot_id: str) -> StoredSnapshot | None:
        return self._read_snapshot("SELECT * FROM recommendation_snapshots WHERE snapshot_id=?", (snapshot_id,))

    def session_snapshot(self, session_id: str) -> StoredSnapshot | None:
        return self._read_snapshot("SELECT s.* FROM sessions x JOIN recommendation_snapshots s ON s.snapshot_id=x.active_snapshot_id WHERE x.session_id=?", (session_id,))

    def ensure_session_snapshot(self, session_id: str, snapshot_id: str) -> None:
        """Bind a session before external LLM work without committing a turn."""
        if not session_id or not snapshot_id:
            raise AgentStoreError("session_or_snapshot_missing")
        with self._transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM recommendation_snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone() is None:
                raise SnapshotIntegrityError("turn_snapshot_missing")
            ts = now_iso()
            conn.execute(
                "INSERT INTO sessions(session_id,active_snapshot_id,created_at,updated_at,next_seq) "
                "VALUES(?,?,?,?,1) ON CONFLICT(session_id) DO NOTHING",
                (session_id, snapshot_id, ts, ts),
            )
            row = conn.execute(
                "SELECT active_snapshot_id FROM sessions WHERE session_id=?", (session_id,)
            ).fetchone()
            if row is None or str(row["active_snapshot_id"]) != snapshot_id:
                raise SessionSnapshotConflict("session_snapshot_already_bound")

    def assistant_turn_payload(
        self,
        session_id: str,
        client_turn_id: str,
        *,
        user_content: str | None = None,
    ) -> dict[str, Any] | None:
        conn = self._connect_read()
        if conn is None:
            return None
        try:
            row = conn.execute(
                """
                SELECT a.payload_json,u.content AS user_content
                FROM turns a
                JOIN turns u
                  ON u.session_id=a.session_id
                 AND u.client_turn_id=a.client_turn_id
                 AND u.role='user'
                WHERE a.session_id=? AND a.client_turn_id=? AND a.role='assistant'
                """,
                (session_id, client_turn_id),
            ).fetchone()
            if row is not None and user_content is not None and str(row["user_content"]) != str(user_content):
                raise AgentStoreError("client_turn_id_content_conflict")
            return json.loads(row["payload_json"]) if row is not None else None
        except sqlite3.OperationalError as exc:
            if self._is_busy(exc):
                raise StorageBusyError(READ_WAIT_MS) from exc
            raise
        finally:
            conn.close()

    def current_book(self) -> MarketBook | None:
        snapshot = self.current_snapshot()
        return self.book_for_snapshot(snapshot) if snapshot else None

    @staticmethod
    def book_for_snapshot(snapshot: StoredSnapshot) -> MarketBook:
        try:
            return MarketBook.model_validate(snapshot.payload["book"])
        except Exception as exc:  # noqa: BLE001
            raise SnapshotIntegrityError("snapshot_book_corrupt") from exc

    def commit_turn(
        self,
        *,
        session_id: str,
        client_turn_id: str,
        user_content: str,
        assistant_content: str,
        assistant_payload: dict[str, Any],
        snapshot_id: str,
        claims: list[dict[str, Any]],
        expected_current_snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        if not session_id or not client_turn_id or not user_content.strip():
            raise AgentStoreError("turn_identity_or_content_invalid")
        with self._transaction() as conn:
            prior = conn.execute(
                """
                SELECT a.payload_json,u.content AS user_content
                FROM turns a
                JOIN turns u
                  ON u.session_id=a.session_id
                 AND u.client_turn_id=a.client_turn_id
                 AND u.role='user'
                WHERE a.session_id=? AND a.client_turn_id=? AND a.role='assistant'
                """,
                (session_id, client_turn_id),
            ).fetchone()
            if prior is not None:
                if str(prior["user_content"]) != str(user_content):
                    raise AgentStoreError("client_turn_id_content_conflict")
                return json.loads(prior["payload_json"])
            if expected_current_snapshot_id is not None:
                current = conn.execute(
                    "SELECT snapshot_id FROM current_snapshot WHERE singleton=1"
                ).fetchone()
                if (
                    current is None
                    or str(current["snapshot_id"])
                    != str(expected_current_snapshot_id)
                ):
                    raise SnapshotIntegrityError(
                        "current_snapshot_changed_before_commit"
                    )
            if conn.execute("SELECT 1 FROM recommendation_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone() is None:
                raise SnapshotIntegrityError("turn_snapshot_missing")
            ts = now_iso()
            conn.execute("INSERT INTO sessions(session_id,active_snapshot_id,created_at,updated_at,next_seq) VALUES(?,?,?,?,1) ON CONFLICT(session_id) DO NOTHING", (session_id, snapshot_id, ts, ts))
            session = conn.execute("SELECT active_snapshot_id,next_seq FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if session is None or session["active_snapshot_id"] != snapshot_id:
                raise SessionSnapshotConflict("session_snapshot_already_bound")
            seq = int(session["next_seq"])
            conn.execute("UPDATE sessions SET next_seq=?,updated_at=? WHERE session_id=?", (seq + 2, ts, session_id))
            user_turn, assistant_turn = gen_id("turn"), gen_id("turn")
            conn.execute("INSERT INTO turns(turn_id,session_id,seq,client_turn_id,role,content,snapshot_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (user_turn, session_id, seq, client_turn_id, "user", user_content, snapshot_id, "{}", ts))
            conn.execute("INSERT INTO turns(turn_id,session_id,seq,client_turn_id,role,content,snapshot_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)", (assistant_turn, session_id, seq + 1, client_turn_id, "assistant", assistant_content, snapshot_id, _canonical_json(assistant_payload), ts))
            for claim in claims:
                conn.execute("INSERT INTO claims(claim_id,turn_id,payload_json,created_at) VALUES(?,?,?,?)", (str(claim.get("claim_id") or gen_id("claim")), assistant_turn, _canonical_json(claim), ts))
            return assistant_payload

    def session_turns(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect_read()
        if conn is None:
            return []
        try:
            rows = conn.execute("SELECT turn_id,seq,role,content,snapshot_id,payload_json,created_at FROM turns WHERE session_id=? ORDER BY seq", (session_id,)).fetchall()
            return [{"turn_id": row["turn_id"], "seq": int(row["seq"]), "role": row["role"], "content": row["content"], "snapshot_id": row["snapshot_id"], "payload": json.loads(row["payload_json"]), "created_at": row["created_at"]} for row in rows]
        except sqlite3.OperationalError as exc:
            if self._is_busy(exc):
                raise StorageBusyError(READ_WAIT_MS) from exc
            raise
        finally:
            conn.close()

    def session_record(self, session_id: str) -> dict[str, Any] | None:
        """Return the immutable-chat session header without creating a session."""
        conn = self._connect_read()
        if conn is None:
            return None
        try:
            row = conn.execute(
                """
                SELECT s.session_id, s.active_snapshot_id, s.created_at, s.updated_at,
                       (
                           SELECT t.turn_id
                           FROM turns t
                           WHERE t.session_id = s.session_id
                           ORDER BY t.seq DESC
                           LIMIT 1
                       ) AS last_turn_id
                FROM sessions s
                WHERE s.session_id = ?
                """,
                (session_id,),
            ).fetchone()
            return dict(row) if row else None
        except sqlite3.OperationalError as exc:
            if self._is_busy(exc):
                raise StorageBusyError(READ_WAIT_MS) from exc
            raise
        finally:
            conn.close()

    def session_overviews(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """List persisted chat sessions for the Workspace read model."""
        conn = self._connect_read()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                """
                SELECT s.session_id, s.active_snapshot_id, s.created_at, s.updated_at,
                       COALESCE((
                           SELECT t.content
                           FROM turns t
                           WHERE t.session_id = s.session_id AND t.role = 'user'
                           ORDER BY t.seq DESC
                           LIMIT 1
                       ), '') AS title,
                       COALESCE((
                           SELECT t.content
                           FROM turns t
                           WHERE t.session_id = s.session_id AND t.role = 'assistant'
                           ORDER BY t.seq DESC
                           LIMIT 1
                       ), '') AS preview
                FROM sessions s
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError as exc:
            if self._is_busy(exc):
                raise StorageBusyError(READ_WAIT_MS) from exc
            raise
        finally:
            conn.close()

    def health_snapshot(self) -> dict[str, Any]:
        conn = self._connect_read()
        empty = {"sessions": 0, "turns": 0, "claims": 0, "snapshots": 0, "current_snapshot_id": None, "path": str(self.path), "snapshot": None}
        if conn is None:
            return empty
        row = None
        current = None
        try:
            conn.execute("BEGIN")
            row = conn.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM sessions) sessions,"
                "(SELECT COUNT(*) FROM turns) turns,"
                "(SELECT COUNT(*) FROM claims) claims,"
                "(SELECT COUNT(*) FROM recommendation_snapshots) snapshots"
            ).fetchone()
            current = conn.execute("SELECT s.* FROM current_snapshot c JOIN recommendation_snapshots s ON s.snapshot_id=c.snapshot_id WHERE c.singleton=1").fetchone()
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError as exc:
            if self._is_busy(exc):
                raise StorageBusyError(READ_WAIT_MS) from exc
            raise
        finally:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            conn.close()
        snapshot = self._decode_snapshot(current) if current else None
        return {"sessions": int(row["sessions"]), "turns": int(row["turns"]), "claims": int(row["claims"]), "snapshots": int(row["snapshots"]), "current_snapshot_id": snapshot.snapshot_id if snapshot else None, "path": str(self.path), "snapshot": snapshot}

    def stats(self) -> dict[str, Any]:
        health = self.health_snapshot()
        return {key: health[key] for key in ("sessions", "turns", "snapshots", "current_snapshot_id", "path")}
