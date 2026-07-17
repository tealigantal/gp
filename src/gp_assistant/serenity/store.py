from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Sequence

from ..core.config import load_config
from ..core.paths import store_dir
from ..runtime.utils import now_iso
from .models import FrozenSerenitySignal, NATIVE_SERENITY_FORMULA_VERSION, SerenityCandidateTarget, SerenityFact, SerenityHypothesis, SerenityPolicyState, SerenityReferenceSnapshot
from .scheduler import trading_day_cooldown_until


_SCHEMA_LOCK = threading.Lock()
_WRITE_LOCK = threading.RLock()
_SCHEMA_READY: set[str] = set()


def serenity_root() -> Path:
    root = Path(os.getenv("GP_SERENITY_STORE_DIR") or str(store_dir() / "serenity"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def evidence_db_path() -> Path:
    return serenity_root() / "evidence.db"


def raw_dir() -> Path:
    path = serenity_root() / "raw"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _connect(*, readonly: bool = False) -> sqlite3.Connection:
    path = evidence_db_path()
    if readonly:
        if not path.exists():
            raise FileNotFoundError(path)
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
    conn = sqlite3.connect(str(path), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=10000")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    db_key = str(evidence_db_path().resolve())
    if db_key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if db_key in _SCHEMA_READY:
            return
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS source_cursors(
                source TEXT PRIMARY KEY,
                cursor_json TEXT NOT NULL,
                schema_fingerprint TEXT,
                last_complete_at TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS poll_runs(
                run_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                elapsed_sec REAL NOT NULL,
                status TEXT NOT NULL,
                complete INTEGER NOT NULL,
                request_count INTEGER NOT NULL,
                item_count INTEGER NOT NULL,
                schema_fingerprint TEXT,
                next_due_at TEXT,
                stale_after_sec REAL,
                error TEXT,
                target_id TEXT,
                target_activation_revision TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_poll_runs_source_finished ON poll_runs(source, finished_at DESC);
            CREATE TABLE IF NOT EXISTS candidate_targets(
                target_id TEXT PRIMARY KEY,
                decision_trade_day TEXT NOT NULL,
                daybook_effective_day TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                symbols_json TEXT NOT NULL,
                input_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_candidate_targets_latest
                ON candidate_targets(created_at DESC);
            CREATE TABLE IF NOT EXISTS active_candidate_target(
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                target_id TEXT NOT NULL,
                activated_at TEXT NOT NULL,
                activation_observed_at TEXT,
                activation_revision TEXT,
                FOREIGN KEY(target_id) REFERENCES candidate_targets(target_id)
            );
            CREATE TABLE IF NOT EXISTS poll_symbol_coverage(
                run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                symbol TEXT NOT NULL,
                metadata_complete INTEGER NOT NULL,
                hydration_complete INTEGER NOT NULL,
                item_count INTEGER NOT NULL,
                window_start TEXT,
                window_end TEXT,
                error TEXT,
                checked_at TEXT NOT NULL,
                PRIMARY KEY(run_id, symbol)
            );
            CREATE INDEX IF NOT EXISTS idx_symbol_coverage_latest
                ON poll_symbol_coverage(source, symbol, checked_at DESC);
            CREATE TABLE IF NOT EXISTS source_progress(
                source TEXT NOT NULL,
                symbol TEXT NOT NULL,
                target_id TEXT,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                next_page INTEGER NOT NULL,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source, symbol)
            );
            CREATE TABLE IF NOT EXISTS bootstrap_runs(
                bootstrap_id TEXT PRIMARY KEY,
                poll_run_id TEXT NOT NULL,
                source TEXT NOT NULL,
                target_checksum TEXT NOT NULL,
                target_count INTEGER NOT NULL,
                lookback_days INTEGER NOT NULL,
                complete INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                completed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_breakers(
                source TEXT PRIMARY KEY,
                reason TEXT NOT NULL,
                opened_at TEXT NOT NULL,
                until_at TEXT NOT NULL,
                sample_hash TEXT
            );
            CREATE TABLE IF NOT EXISTS documents(
                document_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                published_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                current_version_id TEXT,
                current_metadata_version_id TEXT,
                withdrawn INTEGER NOT NULL DEFAULT 0,
                backfill_only INTEGER NOT NULL DEFAULT 0,
                raw_metadata_json TEXT NOT NULL,
                UNIQUE(source, source_record_id)
            );
            CREATE INDEX IF NOT EXISTS idx_documents_symbol ON documents(symbol, first_seen_at DESC);
            CREATE TABLE IF NOT EXISTS document_metadata_versions(
                metadata_version_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                metadata_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                published_at TEXT,
                raw_metadata_json TEXT NOT NULL,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                supersedes_metadata_version_id TEXT,
                FOREIGN KEY(document_id) REFERENCES documents(document_id),
                UNIQUE(document_id, metadata_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_document_metadata_versions
                ON document_metadata_versions(document_id, first_seen_at DESC);
            CREATE TABLE IF NOT EXISTS document_versions(
                version_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                raw_path TEXT,
                extraction_status TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                supersedes_version_id TEXT,
                FOREIGN KEY(document_id) REFERENCES documents(document_id),
                UNIQUE(document_id, content_hash)
            );
            CREATE TABLE IF NOT EXISTS document_checks(
                check_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                checked_at TEXT NOT NULL,
                content_hash TEXT,
                status TEXT NOT NULL,
                FOREIGN KEY(document_id) REFERENCES documents(document_id)
            );
            CREATE TABLE IF NOT EXISTS facts(
                fact_id TEXT PRIMARY KEY,
                version_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                effective_available_at TEXT NOT NULL,
                direction INTEGER NOT NULL,
                verification_state TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(version_id) REFERENCES document_versions(version_id)
            );
            CREATE INDEX IF NOT EXISTS idx_facts_symbol_effective ON facts(symbol, effective_available_at DESC);
            CREATE TABLE IF NOT EXISTS hypotheses(
                hypothesis_id TEXT PRIMARY KEY,
                fact_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                effective_available_at TEXT NOT NULL,
                direction INTEGER NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(fact_id) REFERENCES facts(fact_id)
            );
            CREATE TABLE IF NOT EXISTS reference_snapshots(
                snapshot_id TEXT PRIMARY KEY,
                decision_context_snapshot_id TEXT,
                decision_at TEXT NOT NULL,
                input_checksum TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS serenity_policy_state(
                policy_name TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evaluations(
                evaluation_id TEXT PRIMARY KEY,
                decision_day TEXT NOT NULL,
                matured_at TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                formula_version TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                learning_sample_id TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_evaluations(
                pending_id TEXT PRIMARY KEY,
                reference_snapshot_id TEXT NOT NULL,
                decision_context_snapshot_id TEXT NOT NULL,
                decision_day TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                formula_version TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                evaluated_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pending_status_day ON pending_evaluations(status, decision_day);
            CREATE TABLE IF NOT EXISTS policy_update_ledger(
                update_id TEXT PRIMARY KEY,
                evaluation_id TEXT NOT NULL,
                epoch INTEGER NOT NULL,
                applied_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS worker_lease(
                lease_name TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            """
        )
        document_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "current_metadata_version_id" not in document_columns:
            conn.execute("ALTER TABLE documents ADD COLUMN current_metadata_version_id TEXT")
        if "withdrawn_at" not in document_columns:
            conn.execute("ALTER TABLE documents ADD COLUMN withdrawn_at TEXT")
        conn.execute(
            "UPDATE documents SET withdrawn_at=last_seen_at "
            "WHERE withdrawn=1 AND (withdrawn_at IS NULL OR withdrawn_at='')"
        )
        progress_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(source_progress)").fetchall()
        }
        if "target_id" not in progress_columns:
            conn.execute("ALTER TABLE source_progress ADD COLUMN target_id TEXT")
        poll_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(poll_runs)").fetchall()
        }
        if "target_id" not in poll_columns:
            conn.execute("ALTER TABLE poll_runs ADD COLUMN target_id TEXT")
        if "target_activation_revision" not in poll_columns:
            conn.execute(
                "ALTER TABLE poll_runs ADD COLUMN target_activation_revision TEXT"
            )
        active_target_columns = {
            str(row[1])
            for row in conn.execute(
                "PRAGMA table_info(active_candidate_target)"
            ).fetchall()
        }
        if "activation_observed_at" not in active_target_columns:
            conn.execute(
                "ALTER TABLE active_candidate_target "
                "ADD COLUMN activation_observed_at TEXT"
            )
        if "activation_revision" not in active_target_columns:
            conn.execute(
                "ALTER TABLE active_candidate_target "
                "ADD COLUMN activation_revision TEXT"
            )
        active_rows = conn.execute(
            "SELECT singleton,target_id,activated_at,activation_observed_at,"
            "activation_revision FROM active_candidate_target"
        ).fetchall()
        for active_row in active_rows:
            activated_at = str(
                active_row["activation_observed_at"]
                or active_row["activated_at"]
                or ""
            )
            activation_revision = str(
                active_row["activation_revision"] or ""
            )
            if not activation_revision:
                activation_revision = "seractivation_" + sha256(
                    (
                        f"{active_row['target_id']}|{activated_at}|legacy"
                    ).encode("utf-8")
                ).hexdigest()[:24]
            conn.execute(
                "UPDATE active_candidate_target SET "
                "activation_observed_at=?,activation_revision=? "
                "WHERE singleton=?",
                (activated_at, activation_revision, active_row["singleton"]),
            )
        evaluation_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(evaluations)").fetchall()
        }
        if "learning_sample_id" not in evaluation_columns:
            conn.execute("ALTER TABLE evaluations ADD COLUMN learning_sample_id TEXT")
        legacy_rows = conn.execute(
            "SELECT evaluation_id,payload_json FROM evaluations "
            "WHERE learning_sample_id IS NULL OR learning_sample_id=''"
        ).fetchall()
        for row in legacy_rows:
            try:
                learning_sample_id = str(
                    json.loads(row["payload_json"] or "{}").get("learning_sample_id") or ""
                )
            except Exception:
                learning_sample_id = ""
            if learning_sample_id:
                conn.execute(
                    "UPDATE evaluations SET learning_sample_id=? WHERE evaluation_id=?",
                    (learning_sample_id, str(row["evaluation_id"])),
                )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_evaluations_epoch_sample_day "
            "ON evaluations(epoch,learning_sample_id,decision_day DESC)"
        )
        conn.commit()
        _SCHEMA_READY.add(db_key)


@contextmanager
def write_transaction() -> Iterator[sqlite3.Connection]:
    with _WRITE_LOCK:
        conn = _connect(readonly=False)
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def initialize_store() -> Path:
    conn = _connect(readonly=False)
    conn.close()
    ensure_native_formula_epoch()
    return evidence_db_path()


def ensure_native_formula_epoch() -> Dict[str, Any]:
    """Retire legacy add-on samples and start one auditable native-Alpha epoch.

    The first native cutover retired pending legacy work.  A pre-cutover
    runtime artifact can still be written after that migration, though.  It
    is immutable historical evidence, but cannot be evaluated as a current
    native-Alpha learning sample.
    """

    marker = "native_formula_cutover_v2"
    legacy_formula_reasons = {
        "learning_sample_id_mismatch",
        "reference_content_checksum_mismatch",
        "reference_input_hash_mismatch",
        "reference_decision_snapshot_mismatch",
        "reference_decision_day_mismatch",
        "decision_day_mismatch",
        "formula_version_mismatch",
    }
    with write_transaction() as conn:
        existing = conn.execute(
            "SELECT update_id,epoch FROM policy_update_ledger WHERE evaluation_id=? LIMIT 1",
            (marker,),
        ).fetchone()
        if existing is not None:
            return {
                "changed": False,
                "epoch": int(existing["epoch"]),
                "update_id": str(existing["update_id"]),
            }
        legacy_pending_rows = conn.execute(
            "SELECT pending_id,status,formula_version FROM pending_evaluations WHERE formula_version<>?",
            (NATIVE_SERENITY_FORMULA_VERSION,),
        ).fetchall()
        evaluation_rows = conn.execute(
            "SELECT evaluation_id,payload_json FROM evaluations"
        ).fetchall()
        legacy_evaluation_count = 0
        native_integrity_failures_in_current_epoch = False
        current_policy_row = conn.execute(
            "SELECT payload_json FROM serenity_policy_state WHERE policy_name='serenity'"
        ).fetchone()
        current_epoch = None
        if current_policy_row is not None:
            current_epoch = int(
                SerenityPolicyState.model_validate(
                    json.loads(current_policy_row["payload_json"] or "{}")
                ).epoch
            )

        def native_integrity_failure_is_current(evaluation_payload: Mapping[str, Any]) -> bool:
            errors = [
                str(item)
                for item in list(evaluation_payload.get("integrity_errors") or [])
                if str(item)
            ]
            if not errors:
                return False
            # This exact terminal result came from the old runtime parsing a
            # v2 reference with its v1 model.  Re-validate the frozen payload
            # before excluding it; all other native integrity failures remain
            # hard blockers for a shadow recovery.
            if errors != ["reference_snapshot_unreadable:ValidationError"]:
                return True
            try:
                reference = load_reference_snapshot(
                    str(evaluation_payload.get("reference_snapshot_id") or "")
                )
                if reference is None or reference.input_checksum != str(
                    evaluation_payload.get("input_hash") or ""
                ):
                    return True
                from ..decision_engine.serenity_policy import reference_input_checksum

                return reference_input_checksum(
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
                ) != reference.input_checksum
            except Exception:  # noqa: BLE001
                return True

        for evaluation_row in evaluation_rows:
            try:
                evaluation_payload = json.loads(evaluation_row["payload_json"] or "{}")
            except (TypeError, ValueError):
                legacy_evaluation_count += 1
                continue
            if (
                str(evaluation_payload.get("addon_formula_version") or "")
                != NATIVE_SERENITY_FORMULA_VERSION
            ):
                legacy_evaluation_count += 1
            elif (
                current_epoch is not None
                and int(evaluation_payload.get("epoch") or 0) == current_epoch
                and native_integrity_failure_is_current(evaluation_payload)
            ):
                native_integrity_failures_in_current_epoch = True
        legacy_count = len(legacy_pending_rows) + legacy_evaluation_count
        if legacy_count == 0:
            return {"changed": False, "reason": "no_legacy_formula_state"}

        now = now_iso()
        row = conn.execute(
            "SELECT version,payload_json FROM serenity_policy_state WHERE policy_name='serenity'"
        ).fetchone()
        if row is not None:
            prior = SerenityPolicyState.model_validate(json.loads(row["payload_json"] or "{}"))
            epoch = int(prior.epoch) + 1
            legacy_only_suspension = bool(prior.suspension_reasons) and set(
                prior.suspension_reasons
            ) <= legacy_formula_reasons
            if (
                prior.state == "suspended"
                and legacy_only_suspension
                and not native_integrity_failures_in_current_epoch
            ):
                next_stage = "shadow"
            else:
                next_stage = "suspended" if prior.state == "suspended" else (
                    "shadow" if prior.bootstrap_run_id else "warming"
                )
            transition_raw = (
                f"{prior.transition_log_hash}|{prior.epoch}|{epoch}|"
                f"{NATIVE_SERENITY_FORMULA_VERSION}|{legacy_count}"
            )
            next_state = prior.model_copy(
                update={
                    "version": int(row["version"]) + 1,
                    "epoch": epoch,
                    "state": next_stage,
                    "applied_weight": 0.0,
                    "previous_weight": 0.0,
                    "state_since": now,
                    "last_matured_day": None,
                    "last_evaluation_at": None,
                    "matured_days": 0,
                    "available_results": 0,
                    "decision_snapshots": 0,
                    "supportive_count": 0,
                    "conflicting_count": 0,
                    "consecutive_passes": 0,
                    "consecutive_failures": 0,
                    "probation_matured_days": 0,
                    "probation_available_results": 0,
                    "suspension_reasons": [] if next_stage == "shadow" else list(prior.suspension_reasons),
                    "cooldown_until": None if next_stage == "shadow" else prior.cooldown_until,
                    "rolling_metrics": {},
                    "transition_log_hash": sha256(transition_raw.encode("utf-8")).hexdigest(),
                    "updated_at": now,
                }
            )
        else:
            bootstrap = conn.execute(
                "SELECT bootstrap_id FROM bootstrap_runs WHERE complete=1 ORDER BY completed_at DESC LIMIT 1"
            ).fetchone()
            epoch = 1
            next_state = SerenityPolicyState(
                epoch=epoch,
                state="shadow" if bootstrap else "warming",
                applied_weight=0.0,
                previous_weight=0.0,
                max_weight=load_config().serenity.max_weight,
                state_since=now,
                bootstrap_run_id=str(bootstrap["bootstrap_id"]) if bootstrap else None,
                transition_log_hash=sha256(
                    f"{marker}|{NATIVE_SERENITY_FORMULA_VERSION}|{legacy_count}".encode("utf-8")
                ).hexdigest(),
                updated_at=now,
            )
        conn.execute(
            """
            INSERT INTO serenity_policy_state(policy_name,version,payload_json,updated_at)
            VALUES('serenity',?,?,?)
            ON CONFLICT(policy_name) DO UPDATE SET
                version=excluded.version,payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            (
                next_state.version,
                json.dumps(next_state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True),
                now,
            ),
        )
        retired = conn.execute(
            """
            UPDATE pending_evaluations
            SET status='retired_formula',evaluated_at=?
            WHERE status='pending' AND formula_version<>?
            """,
            (now, NATIVE_SERENITY_FORMULA_VERSION),
        ).rowcount
        ledger_payload = {
            "transition": "native_formula_epoch_cutover_after_legacy_runtime_artifact",
            "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
            "retired_pending_count": int(retired),
            "legacy_record_count": legacy_count,
            "legacy_pending_count": len(legacy_pending_rows),
            "legacy_evaluation_count": legacy_evaluation_count,
            "previous_epoch": int(next_state.epoch) - 1,
            "new_epoch": int(next_state.epoch),
            "recovered_to_shadow": next_state.state == "shadow",
        }
        update_id = "serupd_" + sha256(
            json.dumps(ledger_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        conn.execute(
            "INSERT INTO policy_update_ledger(update_id,evaluation_id,epoch,applied_at,payload_json) VALUES(?,?,?,?,?)",
            (
                update_id,
                marker,
                int(next_state.epoch),
                now,
                json.dumps(ledger_payload, ensure_ascii=False, sort_keys=True),
            ),
        )
        return {"changed": True, "epoch": int(next_state.epoch), **ledger_payload, "update_id": update_id}


def candidate_target_identity_hash(
    symbols: Iterable[str],
    *,
    decision_trade_day: str,
    daybook_effective_day: str,
) -> str:
    clean_symbols = sorted(
        dict.fromkeys(
            str(symbol or "").strip()
            for symbol in symbols
            if str(symbol or "").strip()
        )
    )
    identity = {
        "decision_trade_day": str(decision_trade_day),
        "daybook_effective_day": str(daybook_effective_day),
        "symbols": clean_symbols,
    }
    return sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def publish_candidate_target(
    symbols: Iterable[str],
    *,
    decision_trade_day: str,
    daybook_effective_day: str,
    observed_at: str,
) -> SerenityCandidateTarget:
    clean_symbols = sorted(dict.fromkeys(str(symbol or "").strip() for symbol in symbols if str(symbol or "").strip()))
    if not clean_symbols:
        raise ValueError("serenity_candidate_target_empty")
    input_hash = candidate_target_identity_hash(
        clean_symbols,
        decision_trade_day=decision_trade_day,
        daybook_effective_day=daybook_effective_day,
    )
    target_id = "sertarget_" + input_hash[:24]
    created_at = now_iso()
    with write_transaction() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO candidate_targets(
                target_id,decision_trade_day,daybook_effective_day,observed_at,
                symbols_json,input_hash,created_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                target_id,
                str(decision_trade_day),
                str(daybook_effective_day),
                str(observed_at),
                json.dumps(clean_symbols, ensure_ascii=False),
                input_hash,
                created_at,
            ),
        )
        row = conn.execute(
            "SELECT * FROM candidate_targets WHERE target_id=?", (target_id,)
        ).fetchone()
        active = conn.execute(
            "SELECT target_id,activated_at,activation_observed_at,"
            "activation_revision FROM active_candidate_target WHERE singleton=1"
        ).fetchone()
        if active is None or str(active["target_id"]) != target_id:
            activation_observed_at = str(observed_at)
            activated_at = created_at
            prior_revision = str(active["activation_revision"] or "") if active else ""
            activation_revision = "seractivation_" + sha256(
                (
                    f"{prior_revision}|{target_id}|{activation_observed_at}"
                ).encode("utf-8")
            ).hexdigest()[:24]
            conn.execute(
                """
                INSERT INTO active_candidate_target(
                    singleton,target_id,activated_at,activation_observed_at,
                    activation_revision
                ) VALUES(1,?,?,?,?)
                ON CONFLICT(singleton) DO UPDATE SET
                    target_id=excluded.target_id,
                    activated_at=excluded.activated_at,
                    activation_observed_at=excluded.activation_observed_at,
                    activation_revision=excluded.activation_revision
                """,
                (
                    target_id,
                    activated_at,
                    activation_observed_at,
                    activation_revision,
                ),
            )
        active = conn.execute(
            "SELECT target_id,activated_at,activation_observed_at,"
            "activation_revision FROM active_candidate_target WHERE singleton=1"
        ).fetchone()
    assert row is not None
    assert active is not None
    return SerenityCandidateTarget(
        target_id=str(row["target_id"]),
        decision_trade_day=str(row["decision_trade_day"]),
        daybook_effective_day=str(row["daybook_effective_day"]),
        observed_at=str(active["activation_observed_at"] or row["observed_at"]),
        symbols=list(json.loads(row["symbols_json"] or "[]")),
        input_hash=str(row["input_hash"]),
        created_at=str(row["created_at"]),
        activated_at=str(active["activated_at"]),
        activation_observed_at=str(active["activation_observed_at"]),
        activation_revision=str(active["activation_revision"]),
    )


def load_candidate_target(target_id: str) -> SerenityCandidateTarget | None:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        row = conn.execute(
            "SELECT * FROM candidate_targets WHERE target_id=?", (str(target_id),)
        ).fetchone()
        if row is None:
            return None
        return SerenityCandidateTarget(
            target_id=str(row["target_id"]),
            decision_trade_day=str(row["decision_trade_day"]),
            daybook_effective_day=str(row["daybook_effective_day"]),
            observed_at=str(row["observed_at"]),
            symbols=list(json.loads(row["symbols_json"] or "[]")),
            input_hash=str(row["input_hash"]),
            created_at=str(row["created_at"]),
        )
    finally:
        conn.close()


def load_latest_candidate_target() -> SerenityCandidateTarget | None:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        row = conn.execute(
            """
            SELECT t.*,a.activated_at,a.activation_observed_at,
                   a.activation_revision
            FROM active_candidate_target a
            JOIN candidate_targets t ON t.target_id=a.target_id
            WHERE a.singleton=1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return SerenityCandidateTarget(
        target_id=str(row["target_id"]),
        decision_trade_day=str(row["decision_trade_day"]),
        daybook_effective_day=str(row["daybook_effective_day"]),
        observed_at=str(
            row["activation_observed_at"] or row["observed_at"]
        ),
        symbols=list(json.loads(row["symbols_json"] or "[]")),
        input_hash=str(row["input_hash"]),
        created_at=str(row["created_at"]),
        activated_at=str(row["activated_at"]),
        activation_observed_at=str(row["activation_observed_at"]),
        activation_revision=str(row["activation_revision"]),
    )


def candidate_target_ready(target_id: str, *, decision_at: str | None = None) -> bool:
    target = load_candidate_target(target_id)
    if target is None or not target.symbols:
        return False
    signals = load_frozen_signals(
        target.symbols,
        decision_at=str(decision_at or now_iso()),
        target_id=target.target_id,
    )
    return bool(
        len(signals) == len(target.symbols)
        and all(
            signals[symbol].status in {"available", "no_relevant_evidence"}
            for symbol in target.symbols
        )
    )


def _parse_iso(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        out = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return out if out.tzinfo else out.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def acquire_worker_lease(owner_id: str, *, lease_sec: int | None = None, now: datetime | None = None) -> bool:
    cfg = load_config().serenity
    lease_sec = max(30, int(lease_sec or cfg.lease_sec))
    current = now or datetime.now(timezone.utc)
    heartbeat = current.isoformat()
    expires = (current + timedelta(seconds=lease_sec)).isoformat()
    with write_transaction() as conn:
        row = conn.execute("SELECT owner_id, expires_at FROM worker_lease WHERE lease_name='serenity-worker'").fetchone()
        if row is not None and row["owner_id"] != owner_id:
            existing_expiry = _parse_iso(row["expires_at"])
            if existing_expiry is not None and existing_expiry > current:
                return False
        conn.execute(
            """
            INSERT INTO worker_lease(lease_name, owner_id, heartbeat_at, expires_at)
            VALUES('serenity-worker',?,?,?)
            ON CONFLICT(lease_name) DO UPDATE SET
                owner_id=excluded.owner_id,
                heartbeat_at=excluded.heartbeat_at,
                expires_at=excluded.expires_at
            """,
            (owner_id, heartbeat, expires),
        )
    return True


def heartbeat_worker_lease(owner_id: str, *, lease_sec: int | None = None) -> bool:
    cfg = load_config().serenity
    lease_sec = max(30, int(lease_sec or cfg.lease_sec))
    current = datetime.now(timezone.utc)
    with write_transaction() as conn:
        cur = conn.execute(
            "UPDATE worker_lease SET heartbeat_at=?, expires_at=? WHERE lease_name='serenity-worker' AND owner_id=?",
            (current.isoformat(), (current + timedelta(seconds=lease_sec)).isoformat(), owner_id),
        )
        return cur.rowcount == 1


def release_worker_lease(owner_id: str) -> None:
    with write_transaction() as conn:
        conn.execute("DELETE FROM worker_lease WHERE lease_name='serenity-worker' AND owner_id=?", (owner_id,))


def load_cursor(source: str) -> Dict[str, Any]:
    try:
        conn = _connect(readonly=True)
    except FileNotFoundError:
        return {}
    try:
        row = conn.execute(
            "SELECT cursor_json,schema_fingerprint,last_complete_at,updated_at FROM source_cursors WHERE source=?",
            (source,),
        ).fetchone()
        if row is None:
            return {}
        payload = json.loads(row["cursor_json"] or "{}")
        payload["_schema_fingerprint"] = row["schema_fingerprint"]
        payload["_last_complete_at"] = row["last_complete_at"]
        payload["_updated_at"] = row["updated_at"]
        return payload
    finally:
        conn.close()


def load_source_progress(source: str) -> Dict[str, Dict[str, Any]]:
    try:
        conn = _connect(readonly=True)
    except FileNotFoundError:
        return {}
    try:
        rows = conn.execute("SELECT * FROM source_progress WHERE source=?", (source,)).fetchall()
        return {str(row["symbol"]): dict(row) for row in rows}
    finally:
        conn.close()


def load_source_breaker(source: str) -> Dict[str, Any] | None:
    try:
        conn = _connect(readonly=True)
    except FileNotFoundError:
        return None
    try:
        row = conn.execute("SELECT * FROM source_breakers WHERE source=?", (source,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def set_source_breaker(
    source: str,
    *,
    reason: str,
    until_at: str,
    sample_hash: str | None = None,
) -> None:
    with write_transaction() as conn:
        conn.execute(
            """
            INSERT INTO source_breakers(source,reason,opened_at,until_at,sample_hash)
            VALUES(?,?,?,?,?)
            ON CONFLICT(source) DO UPDATE SET
                reason=excluded.reason,opened_at=excluded.opened_at,
                until_at=excluded.until_at,sample_hash=excluded.sample_hash
            """,
            (source, str(reason)[:240], now_iso(), until_at, sample_hash),
        )


def clear_source_breaker(source: str) -> None:
    with write_transaction() as conn:
        conn.execute("DELETE FROM source_breakers WHERE source=?", (source,))


def lookup_document(source: str, source_record_id: str) -> Dict[str, Any] | None:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        row = conn.execute(
            """
            SELECT d.*,v.content_hash,v.raw_path,v.extraction_status,
                (SELECT MAX(c.checked_at) FROM document_checks c WHERE c.document_id=d.document_id) AS last_content_checked_at
            FROM documents d
            LEFT JOIN document_versions v ON v.version_id=d.current_version_id
            WHERE d.source=? AND d.source_record_id=?
            """,
            (source, str(source_record_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def commit_poll(
    *,
    source: str,
    source_kind: str,
    run: Dict[str, Any],
    records: Sequence[Dict[str, Any]],
    cursor: Dict[str, Any] | None,
    schema_fingerprint: str | None,
    coverage: Sequence[Dict[str, Any]] = (),
    progress: Sequence[Dict[str, Any]] = (),
    lease_owner_id: str | None = None,
) -> Dict[str, int]:
    inserted_documents = 0
    inserted_versions = 0
    inserted_facts = 0
    inserted_hypotheses = 0
    inserted_metadata_versions = 0
    complete = bool(run.get("complete"))
    with write_transaction() as conn:
        if lease_owner_id:
            lease = conn.execute(
                "SELECT owner_id,expires_at FROM worker_lease WHERE lease_name='serenity-worker'"
            ).fetchone()
            lease_expiry = _parse_iso(lease["expires_at"] if lease else None)
            if (
                lease is None
                or str(lease["owner_id"] or "") != str(lease_owner_id)
                or lease_expiry is None
                or lease_expiry <= datetime.now(timezone.utc)
            ):
                raise RuntimeError("serenity_worker_lease_lost_before_commit")
        target_id = str(run.get("target_id") or "")
        if complete and target_id:
            target_row = conn.execute(
                """
                SELECT t.symbols_json,a.target_id AS active_target_id,
                       a.activation_revision
                FROM candidate_targets t
                LEFT JOIN active_candidate_target a ON a.singleton=1
                WHERE t.target_id=?
                """,
                (target_id,),
            ).fetchone()
            expected_symbols = (
                {
                    str(symbol or "").strip()
                    for symbol in json.loads(target_row["symbols_json"] or "[]")
                    if str(symbol or "").strip()
                }
                if target_row is not None
                else set()
            )
            coverage_symbols = [
                str(item.get("symbol") or "").strip() for item in coverage
            ]
            coverage_complete = bool(
                expected_symbols
                and len(coverage_symbols) == len(expected_symbols)
                and set(coverage_symbols) == expected_symbols
                and all(
                    bool(item.get("metadata_complete"))
                    and bool(item.get("hydration_complete"))
                    for item in coverage
                )
            )
            if (
                target_row is None
                or str(target_row["active_target_id"] or "") != target_id
                or not str(run.get("target_activation_revision") or "")
                or str(run.get("target_activation_revision") or "")
                != str(target_row["activation_revision"] or "")
                or str(run.get("status") or "") != "success"
                or not coverage_complete
            ):
                raise RuntimeError("serenity_complete_target_coverage_mismatch")
            try:
                target_stale_after_sec = float(run.get("stale_after_sec"))
            except (TypeError, ValueError):
                target_stale_after_sec = 0.0
            if (
                not math.isfinite(target_stale_after_sec)
                or target_stale_after_sec <= 0.0
            ):
                raise RuntimeError("serenity_complete_target_ttl_invalid")
        for record in records:
            document = dict(record.get("document") or {})
            version = dict(record.get("version") or {})
            make_version_current = bool(version) and bool(version.get("make_current", True))
            doc_id = str(document["document_id"])
            existing = conn.execute(
                "SELECT document_id,current_version_id,current_metadata_version_id,first_seen_at FROM documents WHERE source=? AND source_record_id=?",
                (source, str(document["source_record_id"])),
            ).fetchone()
            raw_metadata_json = json.dumps(
                document.get("raw_metadata") or {}, ensure_ascii=False, sort_keys=True
            )
            metadata_hash = sha256(
                json.dumps(
                    {
                        "title": str(document.get("title") or ""),
                        "source_url": str(document.get("source_url") or ""),
                        "published_at": document.get("published_at"),
                        "raw_metadata": document.get("raw_metadata") or {},
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            ).hexdigest()
            metadata_version_id = "sermeta_" + sha256(
                f"{doc_id}|{metadata_hash}".encode("utf-8")
            ).hexdigest()[:24]
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO documents(
                        document_id,source,source_record_id,symbol,title,source_url,published_at,
                        first_seen_at,last_seen_at,current_version_id,current_metadata_version_id,
                        withdrawn,withdrawn_at,backfill_only,raw_metadata_json
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        doc_id,
                        source,
                        str(document["source_record_id"]),
                        str(document.get("symbol") or ""),
                        str(document.get("title") or ""),
                        str(document.get("source_url") or ""),
                        document.get("published_at"),
                        str(document["first_seen_at"]),
                        str(document.get("last_seen_at") or document["first_seen_at"]),
                        version.get("version_id") if make_version_current else None,
                        metadata_version_id,
                        1 if document.get("withdrawn") else 0,
                        (
                            str(document.get("last_seen_at") or document["first_seen_at"])
                            if document.get("withdrawn")
                            else None
                        ),
                        1 if document.get("backfill_only") else 0,
                        raw_metadata_json,
                    ),
                )
                inserted_documents += 1
            else:
                conn.execute(
                    """
                    UPDATE documents SET title=?,source_url=?,published_at=?,last_seen_at=?,
                        current_version_id=?,current_metadata_version_id=?,
                        withdrawn=CASE WHEN withdrawn=1 OR ?=1 THEN 1 ELSE 0 END,
                        withdrawn_at=CASE
                            WHEN withdrawn=0 AND ?=1 THEN ?
                            ELSE withdrawn_at
                        END,
                        raw_metadata_json=?
                    WHERE document_id=?
                    """,
                    (
                        str(document.get("title") or ""),
                        str(document.get("source_url") or ""),
                        document.get("published_at"),
                        str(document.get("last_seen_at") or document["first_seen_at"]),
                        version.get("version_id") if make_version_current else existing["current_version_id"],
                        metadata_version_id,
                        1 if document.get("withdrawn") else 0,
                        1 if document.get("withdrawn") else 0,
                        str(document.get("last_seen_at") or document.get("first_seen_at") or now_iso()),
                        raw_metadata_json,
                        existing["document_id"],
                    ),
                )
                doc_id = str(existing["document_id"])
            prior_metadata_version_id = (
                str(existing["current_metadata_version_id"] or "") if existing is not None else ""
            )
            metadata_first_seen = str(
                document.get("last_seen_at") or document.get("first_seen_at") or now_iso()
            )
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO document_metadata_versions(
                    metadata_version_id,document_id,metadata_hash,title,source_url,published_at,
                    raw_metadata_json,first_seen_at,last_seen_at,supersedes_metadata_version_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    metadata_version_id,
                    doc_id,
                    metadata_hash,
                    str(document.get("title") or ""),
                    str(document.get("source_url") or ""),
                    document.get("published_at"),
                    raw_metadata_json,
                    metadata_first_seen,
                    metadata_first_seen,
                    prior_metadata_version_id
                    if prior_metadata_version_id and prior_metadata_version_id != metadata_version_id
                    else None,
                ),
            )
            inserted_metadata_versions += max(0, cur.rowcount)
            conn.execute(
                "UPDATE document_metadata_versions SET last_seen_at=? WHERE metadata_version_id=?",
                (metadata_first_seen, metadata_version_id),
            )
            if version:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO document_versions(
                        version_id,document_id,content_hash,raw_path,extraction_status,evidence_json,
                        created_at,supersedes_version_id
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(version["version_id"]),
                        doc_id,
                        str(version.get("content_hash") or ""),
                        version.get("raw_path"),
                        str(version.get("extraction_status") or "metadata_only"),
                        json.dumps(version.get("evidence") or {}, ensure_ascii=False, sort_keys=True),
                        str(version.get("created_at") or now_iso()),
                        version.get("supersedes_version_id"),
                    ),
                )
                inserted_versions += max(0, cur.rowcount)
            check = dict(record.get("check") or {})
            if check:
                check_id = str(check.get("check_id") or "")
                if check_id:
                    conn.execute(
                        "INSERT OR IGNORE INTO document_checks(check_id,document_id,checked_at,content_hash,status) VALUES(?,?,?,?,?)",
                        (
                            check_id,
                            doc_id,
                            str(check.get("checked_at") or now_iso()),
                            check.get("content_hash"),
                            str(check.get("status") or "unknown"),
                        ),
                    )
            for raw_fact in list(record.get("facts") or []):
                fact = raw_fact if isinstance(raw_fact, SerenityFact) else SerenityFact.model_validate(raw_fact)
                payload = fact.model_dump(mode="json")
                cur = conn.execute(
                    "INSERT OR IGNORE INTO facts(fact_id,version_id,symbol,effective_available_at,direction,verification_state,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        fact.fact_id,
                        fact.source_version_id,
                        fact.symbol,
                        fact.effective_available_at,
                        fact.direction,
                        fact.verification_state,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        now_iso(),
                    ),
                )
                inserted_facts += max(0, cur.rowcount)
            for raw_hypothesis in list(record.get("hypotheses") or []):
                hypothesis = raw_hypothesis if isinstance(raw_hypothesis, SerenityHypothesis) else SerenityHypothesis.model_validate(raw_hypothesis)
                payload = hypothesis.model_dump(mode="json")
                cur = conn.execute(
                    "INSERT OR IGNORE INTO hypotheses(hypothesis_id,fact_id,symbol,effective_available_at,direction,status,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        hypothesis.hypothesis_id,
                        hypothesis.fact_id,
                        hypothesis.symbol,
                        hypothesis.effective_available_at,
                        hypothesis.direction,
                        hypothesis.status,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        now_iso(),
                    ),
                )
                inserted_hypotheses += max(0, cur.rowcount)
        conn.execute(
            """
            INSERT OR REPLACE INTO poll_runs(
                run_id,source,source_kind,started_at,finished_at,elapsed_sec,status,complete,
                request_count,item_count,schema_fingerprint,next_due_at,stale_after_sec,error,target_id,
                target_activation_revision
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                str(run["run_id"]),
                source,
                source_kind,
                str(run["started_at"]),
                str(run["finished_at"]),
                float(run.get("elapsed_sec") or 0.0),
                str(run.get("status") or "unknown"),
                1 if complete else 0,
                int(run.get("request_count") or 0),
                int(run.get("item_count") or len(records)),
                schema_fingerprint,
                run.get("next_due_at"),
                float(run.get("stale_after_sec") or 0.0),
                run.get("error"),
                run.get("target_id"),
                run.get("target_activation_revision"),
            ),
        )
        for item in coverage:
            conn.execute(
                """
                INSERT OR REPLACE INTO poll_symbol_coverage(
                    run_id,source,symbol,metadata_complete,hydration_complete,item_count,
                    window_start,window_end,error,checked_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(run["run_id"]),
                    source,
                    str(item.get("symbol") or ""),
                    1 if item.get("metadata_complete") else 0,
                    1 if item.get("hydration_complete") else 0,
                    int(item.get("item_count") or 0),
                    item.get("window_start"),
                    item.get("window_end"),
                    item.get("error"),
                    str(run["finished_at"]),
                ),
            )
        for item in progress:
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            if str(item.get("status") or "") == "complete":
                conn.execute("DELETE FROM source_progress WHERE source=? AND symbol=?", (source, symbol))
                continue
            conn.execute(
                """
                INSERT INTO source_progress(source,symbol,target_id,window_start,window_end,next_page,status,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(source,symbol) DO UPDATE SET
                    target_id=excluded.target_id,window_start=excluded.window_start,window_end=excluded.window_end,
                    next_page=excluded.next_page,status=excluded.status,updated_at=excluded.updated_at
                """,
                (
                    source,
                    symbol,
                    run.get("target_id"),
                    str(item.get("window_start") or ""),
                    str(item.get("window_end") or ""),
                    max(1, int(item.get("next_page") or 1)),
                    str(item.get("status") or "backlog"),
                    now_iso(),
                ),
            )
        if complete and cursor is not None:
            conn.execute(
                """
                INSERT INTO source_cursors(source,cursor_json,schema_fingerprint,last_complete_at,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(source) DO UPDATE SET
                    cursor_json=excluded.cursor_json,
                    schema_fingerprint=COALESCE(excluded.schema_fingerprint,source_cursors.schema_fingerprint),
                    last_complete_at=excluded.last_complete_at,
                    updated_at=excluded.updated_at
                """,
                (
                    source,
                    json.dumps(cursor, ensure_ascii=False, sort_keys=True),
                    schema_fingerprint,
                    str(run["finished_at"]),
                    now_iso(),
                ),
            )
    return {
        "documents": inserted_documents,
        "versions": inserted_versions,
        "facts": inserted_facts,
        "hypotheses": inserted_hypotheses,
        "metadata_versions": inserted_metadata_versions,
    }


def record_bootstrap_run(
    *,
    poll_run_id: str,
    source: str,
    symbols: Sequence[str],
    lookback_days: int,
    complete: bool,
    payload: Dict[str, Any],
) -> str:
    clean_symbols = sorted(dict.fromkeys(str(symbol) for symbol in symbols if str(symbol)))
    target_checksum = sha256("|".join(clean_symbols).encode("utf-8")).hexdigest()
    bootstrap_id = "serboot_" + sha256(
        f"{poll_run_id}|{target_checksum}|{lookback_days}|{int(bool(complete))}".encode("utf-8")
    ).hexdigest()[:24]
    with write_transaction() as conn:
        poll = conn.execute(
            "SELECT finished_at FROM poll_runs WHERE run_id=?", (poll_run_id,)
        ).fetchone()
        completed_at = str(poll["finished_at"]) if poll is not None else now_iso()
        conn.execute(
            """
            INSERT OR IGNORE INTO bootstrap_runs(
                bootstrap_id,poll_run_id,source,target_checksum,target_count,lookback_days,
                complete,payload_json,completed_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                bootstrap_id,
                poll_run_id,
                source,
                target_checksum,
                len(clean_symbols),
                int(lookback_days),
                1 if complete else 0,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                completed_at,
            ),
        )
    return bootstrap_id


def _latest_complete_bootstrap_conn(
    conn: sqlite3.Connection,
    source: str = "cninfo",
    *,
    completed_at_or_before: str | datetime | None = None,
) -> Dict[str, Any] | None:
    rows = conn.execute(
        "SELECT * FROM bootstrap_runs WHERE source=? AND complete=1 ORDER BY completed_at DESC",
        (source,),
    ).fetchall()
    if completed_at_or_before is None:
        return dict(rows[0]) if rows else None
    bound = (
        completed_at_or_before
        if isinstance(completed_at_or_before, datetime)
        else _parse_iso(str(completed_at_or_before))
    )
    if bound is None:
        return None
    for row in rows:
        completed_at = _parse_iso(row["completed_at"])
        if completed_at is not None and completed_at <= bound:
            return dict(row)
    return None


def latest_complete_bootstrap(
    source: str = "cninfo",
    *,
    completed_at_or_before: str | datetime | None = None,
) -> Dict[str, Any] | None:
    try:
        conn = _connect(readonly=True)
    except FileNotFoundError:
        return None
    try:
        return _latest_complete_bootstrap_conn(
            conn,
            source,
            completed_at_or_before=completed_at_or_before,
        )
    finally:
        conn.close()


def recent_poll_durations(source: str, *, limit: int = 20, source_kind: str = "live") -> List[float]:
    try:
        conn = _connect(readonly=True)
    except FileNotFoundError:
        return []
    try:
        rows = conn.execute(
            "SELECT elapsed_sec FROM poll_runs WHERE source=? AND source_kind=? AND complete=1 AND status='success' ORDER BY finished_at DESC LIMIT ?",
            (source, source_kind, max(1, int(limit))),
        ).fetchall()
        return [float(row["elapsed_sec"] or 0.0) for row in reversed(rows)]
    finally:
        conn.close()


def recent_poll_outcomes(source: str, *, limit: int = 20, source_kind: str = "live") -> List[Dict[str, Any]]:
    try:
        conn = _connect(readonly=True)
    except FileNotFoundError:
        return []
    try:
        rows = conn.execute(
            "SELECT status,complete,item_count,elapsed_sec,error FROM poll_runs WHERE source=? AND source_kind=? ORDER BY finished_at DESC LIMIT ?",
            (source, source_kind, max(1, int(limit))),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _last_complete_poll(conn: sqlite3.Connection, source: str = "cninfo") -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM poll_runs WHERE source=? AND complete=1 AND status='success' AND source_kind IN ('live','bootstrap') ORDER BY finished_at DESC LIMIT 1",
        (source,),
    ).fetchone()


def _last_symbol_coverage(
    conn: sqlite3.Connection,
    symbol: str,
    *,
    decision_at: datetime,
    target_id: str | None,
    source: str = "cninfo",
) -> sqlite3.Row | None:
    rows = conn.execute(
        """
        SELECT c.*,p.finished_at,p.stale_after_sec,p.source_kind,p.complete AS poll_complete
        FROM poll_symbol_coverage c
        JOIN poll_runs p ON p.run_id=c.run_id
        WHERE c.source=? AND c.symbol=?
          AND p.source_kind IN ('live','bootstrap')
          AND (? IS NULL OR p.target_id=?)
        ORDER BY c.checked_at DESC
        """,
        (source, symbol, target_id, target_id),
    ).fetchall()
    for row in rows:
        checked_at = _parse_iso(row["checked_at"])
        if checked_at is not None and checked_at <= decision_at:
            return row
    return None


def _target_poll_certificate(
    conn: sqlite3.Connection,
    *,
    target_id: str,
    decision_at: datetime,
    source: str = "cninfo",
) -> Dict[str, Any] | None:
    target = conn.execute(
        """
        SELECT t.symbols_json,t.input_hash,a.activated_at,
               a.activation_observed_at,a.activation_revision
        FROM candidate_targets t
        JOIN active_candidate_target a ON a.target_id=t.target_id
        WHERE a.singleton=1 AND t.target_id=?
        """,
        (str(target_id),),
    ).fetchone()
    if target is None:
        return None
    expected_symbols = {
        str(symbol or "").strip()
        for symbol in json.loads(target["symbols_json"] or "[]")
        if str(symbol or "").strip()
    }
    if not expected_symbols:
        return None
    activation_observed_at = _parse_iso(
        target["activation_observed_at"] or target["activated_at"]
    )
    activation_revision = str(target["activation_revision"] or "")
    if (
        activation_observed_at is None
        or not activation_revision
        or decision_at < activation_observed_at
    ):
        return None
    attempts = conn.execute(
        """
        SELECT * FROM poll_runs
        WHERE source=? AND source_kind='live' AND target_id=?
          AND target_activation_revision=?
        ORDER BY finished_at DESC, run_id DESC
        """,
        (source, str(target_id), activation_revision),
    ).fetchall()
    latest_attempt: sqlite3.Row | None = None
    for row in attempts:
        finished_at = _parse_iso(row["finished_at"])
        if (
            finished_at is not None
            and activation_observed_at <= finished_at <= decision_at
        ):
            latest_attempt = row
            break
    if (
        latest_attempt is None
        or not bool(latest_attempt["complete"])
        or str(latest_attempt["status"] or "") != "success"
    ):
        return None
    rows = conn.execute(
        """
        SELECT c.*,p.finished_at,p.stale_after_sec,p.source_kind,
               p.complete AS poll_complete,p.status AS poll_status
        FROM poll_symbol_coverage c
        JOIN poll_runs p ON p.run_id=c.run_id
        WHERE c.source=? AND c.run_id=?
        ORDER BY c.symbol
        """,
        (source, str(latest_attempt["run_id"])),
    ).fetchall()
    coverage = {str(row["symbol"]): row for row in rows}
    if (
        set(coverage) != expected_symbols
        or len(rows) != len(expected_symbols)
        or any(
            not bool(row["metadata_complete"])
            or not bool(row["hydration_complete"])
            or (_parse_iso(row["checked_at"]) or datetime.max.replace(tzinfo=timezone.utc))
            > decision_at
            for row in rows
        )
    ):
        return None
    revision_payload = {
        "target_id": str(target_id),
        "target_input_hash": str(target["input_hash"] or ""),
        "activation_observed_at": activation_observed_at.isoformat(),
        "activation_revision": activation_revision,
        "source_run_id": str(latest_attempt["run_id"]),
        "finished_at": str(latest_attempt["finished_at"]),
        "stale_after_sec": float(latest_attempt["stale_after_sec"] or 0.0),
        "coverage": [
            {
                "symbol": str(row["symbol"]),
                "checked_at": str(row["checked_at"]),
                "window_start": str(row["window_start"] or ""),
                "window_end": str(row["window_end"] or ""),
                "metadata_complete": bool(row["metadata_complete"]),
                "hydration_complete": bool(row["hydration_complete"]),
            }
            for row in rows
        ],
    }
    readiness_revision = sha256(
        json.dumps(
            revision_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    finished_at = _parse_iso(latest_attempt["finished_at"])
    stale_after_sec = float(latest_attempt["stale_after_sec"] or 0.0)
    if (
        finished_at is None
        or not math.isfinite(stale_after_sec)
        or stale_after_sec <= 0.0
    ):
        return None
    expires_at = (finished_at + timedelta(seconds=stale_after_sec)).isoformat()
    return {
        "target_id": str(target_id),
        "target_input_hash": str(target["input_hash"] or ""),
        "activation_observed_at": activation_observed_at.isoformat(),
        "activation_revision": activation_revision,
        "source_run_id": str(latest_attempt["run_id"]),
        "schema_fingerprint": str(latest_attempt["schema_fingerprint"] or ""),
        "finished_at": str(latest_attempt["finished_at"]),
        "expires_at": expires_at,
        "readiness_revision": readiness_revision,
        "coverage": coverage,
    }


def candidate_target_readiness_revision(
    target_id: str, *, decision_at: str | None = None
) -> Dict[str, Any] | None:
    decision_clock = _parse_iso(str(decision_at or now_iso()))
    if decision_clock is None:
        return None
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        certificate = _target_poll_certificate(
            conn,
            target_id=str(target_id),
            decision_at=decision_clock,
        )
        if certificate is None:
            return None
        expires_at = _parse_iso(certificate.get("expires_at"))
        if expires_at is not None and decision_clock > expires_at:
            return None
        return {
            key: certificate[key]
            for key in (
                "target_id",
                "target_input_hash",
                "activation_observed_at",
                "activation_revision",
                "source_run_id",
                "finished_at",
                "expires_at",
                "readiness_revision",
            )
        }
    finally:
        conn.close()


def load_frozen_signals(
    symbols: Iterable[str],
    *,
    decision_at: str,
    target_id: str | None = None,
    _conn: sqlite3.Connection | None = None,
) -> Dict[str, FrozenSerenitySignal]:
    clean_symbols = list(dict.fromkeys(str(symbol or "").strip() for symbol in symbols if str(symbol or "").strip()))
    generated_at = now_iso()
    if not clean_symbols:
        return {}
    decision_clock = _parse_iso(decision_at)
    if decision_clock is None:
        return {
            symbol: FrozenSerenitySignal(
                symbol=symbol,
                status="not_ready",
                decision_at=str(decision_at or "invalid"),
                generated_at=generated_at,
                input_hash=sha256(f"{symbol}|invalid_decision_at|{decision_at}".encode()).hexdigest(),
                limitations=["decision_at_invalid_fail_closed"],
            )
            for symbol in clean_symbols
        }
    owns_connection = _conn is None
    try:
        conn = _conn or _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return {
            symbol: FrozenSerenitySignal(
                symbol=symbol,
                status="not_ready",
                decision_at=decision_at,
                generated_at=generated_at,
                input_hash=sha256(f"{symbol}|not_ready|{decision_at}".encode()).hexdigest(),
                limitations=["serenity_store_unavailable"],
            )
            for symbol in clean_symbols
        }
    try:
        if owns_connection:
            conn.execute("BEGIN")
        bootstrap_ready = (
            _latest_complete_bootstrap_conn(
                conn, completed_at_or_before=decision_clock
            )
            is not None
        )
        target_certificate = (
            _target_poll_certificate(
                conn,
                target_id=str(target_id),
                decision_at=decision_clock,
            )
            if target_id
            else None
        )
        out: Dict[str, FrozenSerenitySignal] = {}
        for symbol in clean_symbols:
            coverage = (
                target_certificate["coverage"].get(symbol)
                if target_certificate is not None
                else None
            )
            if not target_id:
                coverage = _last_symbol_coverage(
                    conn,
                    symbol,
                    decision_at=decision_clock,
                    target_id=None,
                )
            poll_finished = _parse_iso(coverage["finished_at"] if coverage else None)
            stale_after = float(coverage["stale_after_sec"] or 0.0) if coverage else 0.0
            stale = bool(
                coverage
                and (
                    poll_finished is None
                    or not math.isfinite(stale_after)
                    or stale_after <= 0.0
                    or decision_clock
                    > poll_finished + timedelta(seconds=stale_after)
                )
            )
            version_rows = conn.execute(
                """
                SELECT v.version_id,v.document_id,v.content_hash,v.created_at,
                       d.first_seen_at,d.withdrawn,d.withdrawn_at
                FROM document_versions v
                JOIN documents d ON d.document_id=v.document_id
                WHERE d.symbol=?
                ORDER BY v.created_at DESC,v.version_id DESC
                """,
                (symbol,),
            ).fetchall()
            latest_version_by_document: Dict[str, tuple[datetime, str]] = {}
            for row in version_rows:
                version_seen = _parse_iso(row["created_at"])
                document_seen = _parse_iso(row["first_seen_at"])
                withdrawn_at = _parse_iso(row["withdrawn_at"])
                if version_seen is None or document_seen is None:
                    continue
                if version_seen > decision_clock or document_seen > decision_clock:
                    continue
                if bool(row["withdrawn"]) and withdrawn_at is not None and withdrawn_at <= decision_clock:
                    continue
                document_id = str(row["document_id"])
                prior = latest_version_by_document.get(document_id)
                if prior is None or version_seen > prior[0]:
                    latest_version_by_document[document_id] = (version_seen, str(row["version_id"]))
            latest_version_ids = [value[1] for value in latest_version_by_document.values()]
            if latest_version_ids:
                placeholders = ",".join("?" for _ in latest_version_ids)
                rows = conn.execute(
                    f"""
                    SELECT f.payload_json,f.version_id,v.document_id,v.content_hash,v.created_at,
                           d.first_seen_at,d.withdrawn,d.withdrawn_at
                    FROM facts f
                    JOIN document_versions v ON v.version_id=f.version_id
                    JOIN documents d ON d.document_id=v.document_id
                    WHERE f.symbol=? AND f.version_id IN ({placeholders})
                    ORDER BY v.created_at DESC,f.effective_available_at DESC
                    LIMIT 100
                    """,
                    (symbol, *latest_version_ids),
                ).fetchall()
            else:
                rows = []
            facts: List[SerenityFact] = []
            fact_lineage: Dict[str, Dict[str, Any]] = {}
            expired_fact_ids: List[str] = []
            time_unknown_fact_ids: List[str] = []
            future_fact_ids: List[str] = []
            quarantined_fact_ids: List[str] = []
            unresolved_unscoped_relation_ids: List[str] = []
            relation_candidates: List[
                tuple[SerenityFact, datetime, set[str], set[str]]
            ] = []
            decision_dt = decision_clock
            for row in rows:
                try:
                    fact = SerenityFact.model_validate(json.loads(row["payload_json"] or "{}"))
                except Exception:
                    continue
                effective_dt = _parse_iso(fact.effective_available_at)
                published_dt = _parse_iso(fact.published_at)
                if effective_dt is None or published_dt is None:
                    time_unknown_fact_ids.append(fact.fact_id)
                    continue
                if effective_dt > decision_dt or published_dt > decision_dt:
                    future_fact_ids.append(fact.fact_id)
                    continue
                if decision_dt - published_dt > timedelta(days=load_config().serenity.evidence_ttl_days):
                    expired_fact_ids.append(fact.fact_id)
                    continue
                relation_type = str((fact.numeric_values or {}).get("relation_type") or "")
                relation_target_fact_ids = {
                    str(item)
                    for item in list((fact.numeric_values or {}).get("relation_target_fact_ids") or [])
                    if str(item)
                }
                relation_target_keys = {
                    str(item)
                    for item in list(
                        (fact.numeric_values or {}).get("relation_target_keys") or []
                    )
                    if str(item)
                }
                # Backfill can be shown as reference-only evidence, but can never
                # change the live decision by freezing a fact that arrived later.
                if (
                    relation_type in {"correction", "retraction"}
                    and not fact.backfill_only
                    and (relation_target_keys or relation_target_fact_ids)
                ):
                    relation_candidates.append(
                        (
                            fact,
                            published_dt,
                            relation_target_keys,
                            relation_target_fact_ids,
                        )
                    )
                elif (
                    relation_type in {"correction", "retraction"}
                    and not fact.backfill_only
                ):
                    unresolved_unscoped_relation_ids.append(fact.fact_id)
                if fact.verification_state != "verified":
                    continue
                if float(fact.source_quality) < 0.999:
                    quarantined_fact_ids.append(fact.fact_id)
                    continue
                facts.append(fact)
                fact_lineage[fact.fact_id] = {
                    "document_id": str(row["document_id"]),
                    "version_id": str(row["version_id"]),
                    "content_hash": str(row["content_hash"] or ""),
                    "document_first_seen_at": str(row["first_seen_at"]),
                    "version_first_seen_at": str(row["created_at"]),
                }
            def _is_frozen_by_relation(candidate: SerenityFact) -> bool:
                candidate_published = _parse_iso(candidate.published_at)
                if candidate_published is None:
                    return False
                candidate_relation_key = str(
                    (candidate.numeric_values or {}).get("event_relation_key") or ""
                )
                return any(
                    candidate_published < relation_published
                    and (
                        candidate.fact_id in target_fact_ids
                        or (
                            bool(candidate_relation_key)
                            and candidate_relation_key in relation_target_keys
                        )
                    )
                    for _, relation_published, relation_target_keys, target_fact_ids in relation_candidates
                )

            unverified_relation_ids = [
                fact.fact_id
                for fact, _, _, _ in relation_candidates
                if fact.verification_state != "verified" or float(fact.source_quality) < 0.999
            ]
            frozen_fact_ids = [fact.fact_id for fact in facts if _is_frozen_by_relation(fact)]
            if frozen_fact_ids:
                facts = [fact for fact in facts if fact.fact_id not in set(frozen_fact_ids)]
            facts.sort(
                key=lambda fact: (
                    -float((_parse_iso(fact.effective_available_at) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()),
                    -float((_parse_iso(fact.published_at) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()),
                    -float(fact.confidence),
                    str(fact.fact_id),
                )
            )
            live_directional = [
                fact for fact in facts if fact.direction != 0 and not fact.backfill_only
            ][:3]
            backfill_directional = [
                fact for fact in facts if fact.direction != 0 and fact.backfill_only
            ][:3]
            primary_directional = live_directional or backfill_directional
            ordered_facts = [
                *primary_directional,
                *(fact for fact in facts if fact.fact_id not in {item.fact_id for item in primary_directional}),
            ]
            facts = ordered_facts[:3]
            if not bootstrap_ready or coverage is None:
                status = "not_ready"
            elif not bool(coverage["metadata_complete"]) or not bool(coverage["hydration_complete"]):
                status = "source_error"
            elif stale:
                status = "stale"
            elif unresolved_unscoped_relation_ids:
                status = "source_error"
            elif live_directional:
                status = "available"
            else:
                status = "no_relevant_evidence"
            scored = list(live_directional)
            learning_eligible = bool(scored)
            weighted_terms = [
                float(f.direction) * float(f.confidence) * float(f.source_quality)
                for f in scored
            ]
            weighted = sum(weighted_terms)
            alpha_value = max(-1.0, min(1.0, weighted / max(1, len(weighted_terms))))
            direction = -1 if weighted < -1e-12 else 1 if weighted > 1e-12 else 0
            availability = 1 if status == "available" and scored else 0
            confidence = min(1.0, sum(abs(value) for value in weighted_terms) / max(1, len(weighted_terms)))
            source_quality = (
                sum(float(f.source_quality) for f in scored) / len(scored)
                if scored
                else 0.0
            )
            payload = [fact.model_dump(mode="json") for fact in facts]
            lineage = {
                "target_id": target_id,
                "source_run_id": str(coverage["run_id"]) if coverage else None,
                "readiness_revision": (
                    str(target_certificate["readiness_revision"])
                    if target_certificate is not None
                    else None
                ),
                "activation_observed_at": (
                    str(target_certificate["activation_observed_at"])
                    if target_certificate is not None
                    else None
                ),
                "activation_revision": (
                    str(target_certificate["activation_revision"])
                    if target_certificate is not None
                    else None
                ),
                "poll_finished_at": (
                    str(target_certificate["finished_at"])
                    if target_certificate is not None
                    else None
                ),
                "poll_expires_at": (
                    str(target_certificate["expires_at"])
                    if target_certificate is not None
                    else None
                ),
                "source_schema_fingerprint": (
                    str(target_certificate["schema_fingerprint"])
                    if target_certificate is not None
                    else None
                ),
                "coverage_checked_at": str(coverage["checked_at"]) if coverage else None,
                "coverage_window_start": str(coverage["window_start"] or "") if coverage else None,
                "coverage_window_end": str(coverage["window_end"] or "") if coverage else None,
                "coverage_metadata_complete": (
                    bool(coverage["metadata_complete"]) if coverage else False
                ),
                "coverage_hydration_complete": (
                    bool(coverage["hydration_complete"]) if coverage else False
                ),
                "coverage_item_count": int(coverage["item_count"] or 0) if coverage else 0,
                "facts": {
                    fact.fact_id: fact_lineage.get(fact.fact_id, {})
                    for fact in facts
                },
            }
            digest = sha256(
                json.dumps(
                    {
                        "symbol": symbol,
                        "decision_at": decision_at,
                        "target_id": target_id,
                        "status": status,
                        "alpha_value": alpha_value,
                        "facts": payload,
                        "lineage": lineage,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            hypothesis_ids: List[str] = []
            if facts:
                placeholders = ",".join("?" for _ in facts)
                hrows = conn.execute(
                    f"SELECT hypothesis_id FROM hypotheses WHERE fact_id IN ({placeholders}) ORDER BY created_at DESC",
                    tuple(f.fact_id for f in facts),
                ).fetchall()
                hypothesis_ids = [str(row["hypothesis_id"]) for row in hrows]
            limitations = []
            if status == "stale":
                limitations.append("source_stale_no_ranking_effect")
            if status == "no_relevant_evidence":
                limitations.append("complete_poll_found_no_scored_evidence")
            if expired_fact_ids:
                limitations.append("expired_evidence_excluded:" + ",".join(expired_fact_ids[:3]))
            if time_unknown_fact_ids:
                limitations.append("published_time_missing_excluded:" + ",".join(time_unknown_fact_ids[:3]))
            if future_fact_ids:
                limitations.append("future_timestamp_evidence_excluded:" + ",".join(future_fact_ids[:3]))
            if quarantined_fact_ids:
                limitations.append("legacy_unverified_fact_quarantined:" + ",".join(quarantined_fact_ids[:3]))
            if unresolved_unscoped_relation_ids:
                limitations.append(
                    "unresolved_relation_target_unknown_no_ranking_effect:"
                    + ",".join(unresolved_unscoped_relation_ids[:3])
                )
            if unverified_relation_ids:
                limitations.append("unverified_correction_freezes_prior_evidence:" + ",".join(unverified_relation_ids[:3]))
            if frozen_fact_ids and not any(fact.direction != 0 for fact in facts):
                limitations.append("unresolved_correction_relation_no_ranking_effect")
            out[symbol] = FrozenSerenitySignal(
                symbol=symbol,
                status=status,
                availability=availability,
                learning_eligible=bool(availability and learning_eligible),
                direction=direction if availability else 0,
                confidence=confidence if availability else 0.0,
                source_quality=source_quality if availability else 0.0,
                alpha_value=alpha_value if availability else 0.0,
                decision_at=decision_at,
                generated_at=generated_at,
                target_id=target_id,
                source_run_id=str(coverage["run_id"]) if coverage else None,
                evidence_count=len(facts),
                fact_ids=[fact.fact_id for fact in facts],
                hypothesis_ids=hypothesis_ids,
                facts=facts,
                lineage=lineage,
                input_hash=digest,
                limitations=limitations,
            )
        return out
    finally:
        if owns_connection:
            if conn.in_transaction:
                conn.rollback()
            conn.close()


def serenity_batch_semantic_revision(
    signals: Mapping[str, FrozenSerenitySignal],
    *,
    target_id: str,
    target_input_hash: str,
    activation_observed_at: str,
    activation_revision: str,
    formula_version: str,
    policy_snapshot: Mapping[str, Any],
) -> str:
    """Hash only evidence and policy state that can change the decision.

    Poll/run timestamps remain part of the immutable audit attestation and the
    live freshness certificate, but an equivalent successful poll must not
    invalidate an already-published decision snapshot.
    """

    clean_target = str(target_id or "")
    clean_hash = str(target_input_hash or "")
    clean_activation = str(activation_revision or "")
    clean_formula = str(formula_version or "")
    if not signals or not all(
        (clean_target, clean_hash, activation_observed_at, clean_activation, clean_formula)
    ):
        return ""
    try:
        normalized_policy = {
            "mode": str(policy_snapshot.get("mode") or ""),
            "state": str(policy_snapshot.get("state") or ""),
            "epoch": int(policy_snapshot.get("epoch") or 0),
            "applied_weight": float(policy_snapshot.get("applied_weight") or 0.0),
            "max_weight": float(policy_snapshot.get("max_weight") or 0.0),
            "native_required": policy_snapshot.get("native_required") is True,
        }
    except (TypeError, ValueError):
        return ""
    if (
        normalized_policy["mode"] != "native"
        or normalized_policy["epoch"] < 1
        or not normalized_policy["native_required"]
        or not math.isfinite(normalized_policy["applied_weight"])
        or not math.isfinite(normalized_policy["max_weight"])
    ):
        return ""

    semantic_signals: Dict[str, Any] = {}
    for symbol, raw_signal in sorted(signals.items()):
        signal = (
            raw_signal
            if isinstance(raw_signal, FrozenSerenitySignal)
            else FrozenSerenitySignal.model_validate(raw_signal)
        )
        if str(signal.symbol or "") != str(symbol) or str(signal.target_id or "") != clean_target:
            return ""
        semantic_signals[str(symbol)] = {
            "symbol": str(signal.symbol),
            "status": str(signal.status),
            "availability": int(signal.availability),
            "learning_eligible": bool(signal.learning_eligible),
            "direction": int(signal.direction),
            "confidence": float(signal.confidence),
            "source_quality": float(signal.source_quality),
            "alpha_value": float(signal.alpha_value),
            "evidence_count": int(signal.evidence_count),
            # Fact order is decision-visible: the deterministic narration
            # projection exposes the first two facts.  Preserve the frozen
            # ordering instead of treating a reorder as equivalent.
            "fact_ids": [str(item) for item in signal.fact_ids],
            "facts": [
                fact.model_dump(mode="json") for fact in signal.facts
            ],
            "fact_lineage": dict((signal.lineage or {}).get("facts") or {}),
        }
    observed = _parse_iso(str(activation_observed_at))
    payload = {
        "schema": "SerenitySemanticRevision.v1",
        "target_id": clean_target,
        "target_input_hash": clean_hash,
        "activation_observed_at": (
            observed.isoformat() if observed is not None else str(activation_observed_at)
        ),
        "activation_revision": clean_activation,
        "formula_version": clean_formula,
        "policy": normalized_policy,
        "signals": semantic_signals,
    }
    return sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _default_policy_state() -> SerenityPolicyState:
    now = now_iso()
    cfg = load_config().serenity
    return SerenityPolicyState(
        state="off" if cfg.mode == "off" else "warming",
        applied_weight=0.0,
        max_weight=cfg.max_weight,
        state_since=now,
        updated_at=now,
    )


def load_policy_state() -> SerenityPolicyState:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return _default_policy_state()
    try:
        row = conn.execute(
            "SELECT version,payload_json FROM serenity_policy_state WHERE policy_name='serenity'"
        ).fetchone()
        if row is None:
            return _default_policy_state()
        try:
            return SerenityPolicyState.model_validate(json.loads(row["payload_json"] or "{}"))
        except Exception:
            fallback = _default_policy_state()
            if fallback.state == "off":
                return fallback
            return fallback.model_copy(
                update={
                    "version": int(row["version"] or fallback.version),
                    "state": "suspended",
                    "applied_weight": 0.0,
                    "suspension_reasons": ["policy_state_invalid_fail_closed"],
                }
            )
    finally:
        conn.close()


def current_native_readiness_state(
    target_id: str | None = None, *, decision_at: str | None = None
) -> Dict[str, Any]:
    """Read the current target, poll certificate, policy and lease atomically."""

    decision_clock = _parse_iso(str(decision_at or now_iso()))
    if decision_clock is None:
        raise RuntimeError("serenity_readiness_clock_invalid")
    cfg = load_config().serenity
    conn = _connect(readonly=True)
    try:
        conn.execute("BEGIN")
        active = conn.execute(
            """
            SELECT t.target_id,t.input_hash,t.symbols_json,a.activated_at,
                   a.activation_observed_at,a.activation_revision
            FROM active_candidate_target a
            JOIN candidate_targets t ON t.target_id=a.target_id
            WHERE a.singleton=1
            """
        ).fetchone()
        active_target_id = str(active["target_id"] or "") if active else ""
        requested_target_id = str(target_id or active_target_id)
        certificate = (
            _target_poll_certificate(
                conn,
                target_id=requested_target_id,
                decision_at=decision_clock,
            )
            if active_target_id and requested_target_id == active_target_id
            else None
        )
        policy_row = conn.execute(
            "SELECT version,payload_json FROM serenity_policy_state "
            "WHERE policy_name='serenity'"
        ).fetchone()
        if policy_row is None:
            policy = _default_policy_state()
        else:
            try:
                policy = SerenityPolicyState.model_validate(
                    json.loads(policy_row["payload_json"] or "{}")
                )
            except Exception:
                fallback = _default_policy_state()
                policy = fallback.model_copy(
                    update={
                        "version": int(policy_row["version"] or fallback.version),
                        "state": "suspended",
                        "applied_weight": 0.0,
                        "suspension_reasons": [
                            "policy_state_invalid_fail_closed"
                        ],
                    }
                )
        bootstrap = conn.execute(
            "SELECT bootstrap_id FROM bootstrap_runs "
            "WHERE source='cninfo' AND complete=1 "
            "ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        heartbeat = conn.execute(
            "SELECT owner_id,heartbeat_at,expires_at FROM worker_lease "
            "WHERE lease_name='serenity-worker'"
        ).fetchone()
        lease_expires_at = _parse_iso(
            heartbeat["expires_at"] if heartbeat else None
        )
        worker_alive = bool(
            heartbeat is not None
            and lease_expires_at is not None
            and lease_expires_at > decision_clock
        )
        effective_weight = (
            max(
                0.0,
                min(
                    float(policy.max_weight),
                    0.08,
                    round(float(policy.applied_weight), 2),
                ),
            )
            if cfg.mode == "native"
            and policy.state in {"probation", "active"}
            and bool(policy.bootstrap_run_id)
            else 0.0
        )
        active_symbols = (
            sorted(
                {
                    str(symbol or "").strip()
                    for symbol in json.loads(active["symbols_json"] or "[]")
                    if str(symbol or "").strip()
                }
            )
            if active is not None
            else []
        )
        semantic_signals: Dict[str, FrozenSerenitySignal] = {}
        if certificate is not None and active_symbols:
            try:
                semantic_signals = load_frozen_signals(
                    active_symbols,
                    decision_at=decision_clock.isoformat(),
                    target_id=active_target_id,
                    _conn=conn,
                )
            except Exception:
                semantic_signals = {}
        semantic_ready = bool(
            certificate is not None
            and set(semantic_signals) == set(active_symbols)
            and all(
                signal.status in {"available", "no_relevant_evidence"}
                and str(signal.target_id or "") == active_target_id
                and str(signal.source_run_id or "")
                == str(certificate.get("source_run_id") or "")
                and str((signal.lineage or {}).get("readiness_revision") or "")
                == str(certificate.get("readiness_revision") or "")
                for signal in semantic_signals.values()
            )
        )
        semantic_revision = (
            serenity_batch_semantic_revision(
                semantic_signals,
                target_id=active_target_id,
                target_input_hash=str(active["input_hash"] or "") if active else "",
                activation_observed_at=(
                    str(active["activation_observed_at"] or "") if active else ""
                ),
                activation_revision=(
                    str(active["activation_revision"] or "") if active else ""
                ),
                formula_version=NATIVE_SERENITY_FORMULA_VERSION,
                policy_snapshot={
                    "mode": str(cfg.mode),
                    "state": str(policy.state),
                    "epoch": int(policy.epoch),
                    "applied_weight": float(effective_weight),
                    "max_weight": float(policy.max_weight),
                    "native_required": True,
                },
            )
            if semantic_ready
            else ""
        )
        expires_at = _parse_iso(
            certificate.get("expires_at") if certificate else None
        )
        certificate_current = bool(
            certificate is not None
            and expires_at is not None
            and decision_clock <= expires_at
        )
        freshness_binding = {
            "mode": str(cfg.mode),
            "formula_version": NATIVE_SERENITY_FORMULA_VERSION,
            "target_id": active_target_id,
            "target_input_hash": (
                str(active["input_hash"] or "") if active else ""
            ),
            "activation_observed_at": (
                str(active["activation_observed_at"] or "") if active else ""
            ),
            "activation_revision": (
                str(active["activation_revision"] or "") if active else ""
            ),
            "source_run_id": (
                str(certificate.get("source_run_id") or "")
                if certificate
                else ""
            ),
            "readiness_revision": (
                str(certificate.get("readiness_revision") or "")
                if certificate
                else ""
            ),
            "poll_finished_at": (
                str(certificate.get("finished_at") or "")
                if certificate
                else ""
            ),
            "poll_expires_at": (
                str(certificate.get("expires_at") or "")
                if certificate
                else ""
            ),
            "coverage_digest": (
                str(certificate.get("readiness_revision") or "")
                if certificate
                else ""
            ),
            "semantic_revision": semantic_revision,
            "policy_state": str(policy.state),
            "policy_epoch": int(policy.epoch),
            "policy_applied_weight": float(effective_weight),
            "policy_max_weight": float(policy.max_weight),
            "native_required": True,
        }
        semantic_binding = {
            key: value
            for key, value in freshness_binding.items()
            if key
            not in {
                "source_run_id",
                "readiness_revision",
                "poll_finished_at",
                "poll_expires_at",
                "coverage_digest",
            }
        }
        binding_token = sha256(
            json.dumps(
                semantic_binding,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        freshness_token = sha256(
            json.dumps(
                freshness_binding,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return {
            **freshness_binding,
            "binding_token": binding_token,
            "freshness_token": freshness_token,
            "requested_target_id": requested_target_id,
            "target_matches": bool(
                requested_target_id and requested_target_id == active_target_id
            ),
            "certificate_current": certificate_current,
            "semantic_ready": semantic_ready,
            "bootstrap_ready": bootstrap is not None,
            "bootstrap_run_id": (
                str(bootstrap["bootstrap_id"]) if bootstrap else None
            ),
            "worker_alive": worker_alive,
            "worker_owner_id": (
                str(heartbeat["owner_id"] or "") if heartbeat else None
            ),
            "worker_heartbeat_at": (
                str(heartbeat["heartbeat_at"] or "") if heartbeat else None
            ),
            "worker_lease_expires_at": (
                str(heartbeat["expires_at"] or "") if heartbeat else None
            ),
            "available": bool(
                cfg.mode == "native"
                and requested_target_id == active_target_id
                and certificate_current
                and semantic_ready
                and bool(semantic_revision)
                and bootstrap is not None
                and worker_alive
            ),
        }
    finally:
        conn.close()


def save_policy_state(state: SerenityPolicyState, *, expected_version: int | None = None) -> SerenityPolicyState:
    state = SerenityPolicyState.model_validate(state.model_dump(mode="json"))
    next_state = state.model_copy(update={"version": int(state.version) + 1, "updated_at": now_iso()})
    payload = json.dumps(next_state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    with write_transaction() as conn:
        row = conn.execute("SELECT version FROM serenity_policy_state WHERE policy_name='serenity'").fetchone()
        current_version = int(row["version"]) if row else 0
        expected = int(expected_version if expected_version is not None else state.version)
        if row is not None and current_version != expected:
            raise RuntimeError(f"serenity_policy_cas_conflict:{current_version}!={expected}")
        conn.execute(
            """
            INSERT INTO serenity_policy_state(policy_name,version,payload_json,updated_at)
            VALUES('serenity',?,?,?)
            ON CONFLICT(policy_name) DO UPDATE SET
                version=excluded.version,payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            (next_state.version, payload, next_state.updated_at),
        )
    return next_state


def save_policy_state_with_ledger(
    state: SerenityPolicyState,
    *,
    expected_version: int,
    evaluation_id: str,
    ledger_payload: Dict[str, Any],
) -> SerenityPolicyState:
    state = SerenityPolicyState.model_validate(state.model_dump(mode="json"))
    next_state = state.model_copy(update={"version": int(state.version) + 1, "updated_at": now_iso()})
    state_payload = json.dumps(next_state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    ledger_json = json.dumps(ledger_payload, ensure_ascii=False, sort_keys=True, default=str)
    update_id = "serupd_" + sha256(
        f"{evaluation_id}|{next_state.epoch}|{ledger_json}".encode("utf-8")
    ).hexdigest()[:24]
    with write_transaction() as conn:
        row = conn.execute("SELECT version FROM serenity_policy_state WHERE policy_name='serenity'").fetchone()
        current_version = int(row["version"]) if row else 0
        if row is not None and current_version != int(expected_version):
            raise RuntimeError(f"serenity_policy_cas_conflict:{current_version}!={expected_version}")
        conn.execute(
            """
            INSERT INTO serenity_policy_state(policy_name,version,payload_json,updated_at)
            VALUES('serenity',?,?,?)
            ON CONFLICT(policy_name) DO UPDATE SET
                version=excluded.version,payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """,
            (next_state.version, state_payload, next_state.updated_at),
        )
        conn.execute(
            "INSERT OR IGNORE INTO policy_update_ledger(update_id,evaluation_id,epoch,applied_at,payload_json) VALUES(?,?,?,?,?)",
            (update_id, evaluation_id, int(next_state.epoch), next_state.updated_at, ledger_json),
        )
    return next_state


def suspend_policy(reason: str) -> SerenityPolicyState:
    clean_reason = str(reason or "serenity_integrity_failure")[:240]
    for _ in range(3):
        state = load_policy_state()
        if state.state == "off":
            return state
        if state.state == "suspended" and state.applied_weight == 0.0 and clean_reason in state.suspension_reasons:
            return state
        now = datetime.now(timezone.utc)
        transition_raw = (
            f"{state.transition_log_hash}|{state.epoch}|{state.state}|{state.applied_weight}|"
            f"suspended|0.0|{clean_reason}|{now.isoformat()}"
        )
        next_state = state.model_copy(
            update={
                "state": "suspended",
                "previous_weight": state.applied_weight,
                "applied_weight": 0.0,
                "state_since": now.isoformat(),
                "cooldown_until": trading_day_cooldown_until(now, trading_days=10),
                "suspension_reasons": list(dict.fromkeys([*state.suspension_reasons, clean_reason])),
                "consecutive_passes": 0,
                "transition_log_hash": sha256(transition_raw.encode("utf-8")).hexdigest(),
            }
        )
        try:
            return save_policy_state_with_ledger(
                next_state,
                expected_version=state.version,
                evaluation_id="suspend_" + sha256(clean_reason.encode("utf-8")).hexdigest()[:16],
                ledger_payload={
                    "transition": "suspended",
                    "reason": clean_reason,
                    "from_state": state.state,
                    "from_weight": state.applied_weight,
                    "to_weight": 0.0,
                },
            )
        except RuntimeError as ex:
            if not str(ex).startswith("serenity_policy_cas_conflict"):
                raise
    raise RuntimeError("serenity_policy_cas_conflict_exhausted")


_OPERATIONAL_SUSPENSION_REASONS = {
    "three_consecutive_source_or_parse_failures",
    "recent_20_source_success_below_90pct",
    "source_success_below_90pct",
}


def recover_operational_suspension_after_complete_poll() -> SerenityPolicyState:
    """Move an old source-health suspension to shadow after a real complete poll.

    Source readiness now blocks the candidate set directly.  It must not share
    the causal-performance suspension state or retain a stale ten-day cooldown.
    Integrity and performance suspensions remain untouched.
    """

    for _ in range(3):
        state = load_policy_state()
        reasons = set(state.suspension_reasons)
        if state.state != "suspended" or not reasons or not reasons <= _OPERATIONAL_SUSPENSION_REASONS:
            return state
        transition_raw = (
            f"{state.transition_log_hash}|{state.epoch}|suspended|0.0|shadow|0.0|"
            f"source_recovered|{now_iso()}"
        )
        next_state = state.model_copy(
            update={
                "state": "shadow",
                "previous_weight": 0.0,
                "applied_weight": 0.0,
                "state_since": now_iso(),
                "cooldown_until": None,
                "suspension_reasons": [],
                "consecutive_failures": 0,
                "consecutive_passes": 0,
                "transition_log_hash": sha256(transition_raw.encode("utf-8")).hexdigest(),
            }
        )
        try:
            return save_policy_state_with_ledger(
                next_state,
                expected_version=state.version,
                evaluation_id="source_recovered_" + sha256(transition_raw.encode("utf-8")).hexdigest()[:16],
                ledger_payload={
                    "transition": "operational_source_recovered_to_shadow",
                    "cleared_reasons": sorted(reasons),
                },
            )
        except RuntimeError as ex:
            if not str(ex).startswith("serenity_policy_cas_conflict"):
                raise
    raise RuntimeError("serenity_policy_cas_conflict_exhausted")


def ensure_shadow_ready(bootstrap_run_id: str) -> SerenityPolicyState:
    bootstrap = latest_complete_bootstrap()
    if bootstrap is None or str(bootstrap.get("bootstrap_id") or "") != str(bootstrap_run_id or ""):
        raise RuntimeError("serenity_bootstrap_marker_missing_or_incomplete")
    state = load_policy_state()
    if (
        state.state in {"warming", "off"}
        or (state.state == "shadow" and not state.bootstrap_run_id)
    ) and load_config().serenity.mode != "off":
        state = state.model_copy(
            update={
                "state": "shadow",
                "applied_weight": 0.0,
                "state_since": now_iso(),
                "bootstrap_run_id": bootstrap_run_id,
            }
        )
        return save_policy_state_with_ledger(
            state,
            expected_version=state.version,
            evaluation_id=str(bootstrap_run_id),
            ledger_payload={
                "transition": "shadow_ready",
                "bootstrap_run_id": str(bootstrap_run_id),
            },
        )
    return state


def save_reference_snapshot(snapshot: SerenityReferenceSnapshot) -> str:
    payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    with write_transaction() as conn:
        existing = conn.execute(
            "SELECT payload_json FROM reference_snapshots WHERE snapshot_id=?",
            (snapshot.snapshot_id,),
        ).fetchone()
        if existing is not None and json.loads(existing["payload_json"] or "{}") != json.loads(payload):
            raise RuntimeError("serenity_reference_snapshot_immutable_conflict")
        conn.execute(
            "INSERT OR IGNORE INTO reference_snapshots(snapshot_id,decision_context_snapshot_id,decision_at,input_checksum,payload_json,created_at) VALUES(?,?,?,?,?,?)",
            (
                snapshot.snapshot_id,
                snapshot.decision_context_snapshot_id,
                snapshot.decision_at,
                snapshot.input_checksum,
                payload,
                snapshot.created_at,
            ),
        )
    return snapshot.snapshot_id


def enqueue_pending_evaluation(
    *,
    reference_snapshot_id: str,
    decision_context_snapshot_id: str,
    decision_day: str,
    epoch: int,
    formula_version: str,
    input_hash: str,
) -> str:
    pending_id = pending_evaluation_id(
        reference_snapshot_id=reference_snapshot_id,
        decision_context_snapshot_id=decision_context_snapshot_id,
        epoch=epoch,
        formula_version=formula_version,
    )
    with write_transaction() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO pending_evaluations(
                pending_id,reference_snapshot_id,decision_context_snapshot_id,decision_day,
                epoch,formula_version,input_hash,status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                pending_id,
                reference_snapshot_id,
                decision_context_snapshot_id,
                decision_day,
                int(epoch),
                formula_version,
                input_hash,
                "pending",
                now_iso(),
            ),
        )
    return pending_id


def pending_evaluation_id(
    *,
    reference_snapshot_id: str,
    decision_context_snapshot_id: str,
    epoch: int,
    formula_version: str,
) -> str:
    raw = (
        f"{reference_snapshot_id}|{decision_context_snapshot_id}|"
        f"{int(epoch)}|{formula_version}"
    )
    return "serpending_" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def save_reference_and_enqueue_pending(
    snapshot: SerenityReferenceSnapshot,
    *,
    decision_day: str,
    epoch: int,
    formula_version: str,
) -> tuple[str, str]:
    """Atomically persist the immutable sidecar and its opaque maturity job."""

    if not snapshot.decision_context_snapshot_id:
        raise ValueError("serenity_decision_snapshot_reference_required")
    if str(snapshot.decision_day) != str(decision_day):
        raise ValueError("serenity_reference_decision_day_mismatch")
    pending_id = pending_evaluation_id(
        reference_snapshot_id=snapshot.snapshot_id,
        decision_context_snapshot_id=snapshot.decision_context_snapshot_id,
        epoch=epoch,
        formula_version=formula_version,
    )
    payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    created_at = now_iso()
    with write_transaction() as conn:
        existing = conn.execute(
            "SELECT payload_json FROM reference_snapshots WHERE snapshot_id=?",
            (snapshot.snapshot_id,),
        ).fetchone()
        if existing is not None and json.loads(existing["payload_json"] or "{}") != json.loads(payload):
            raise RuntimeError("serenity_reference_snapshot_immutable_conflict")
        conn.execute(
            "INSERT OR IGNORE INTO reference_snapshots(snapshot_id,decision_context_snapshot_id,decision_at,input_checksum,payload_json,created_at) VALUES(?,?,?,?,?,?)",
            (
                snapshot.snapshot_id,
                snapshot.decision_context_snapshot_id,
                snapshot.decision_at,
                snapshot.input_checksum,
                payload,
                snapshot.created_at,
            ),
        )
        existing_pending = conn.execute(
            """
            SELECT reference_snapshot_id,decision_context_snapshot_id,decision_day,
                   epoch,formula_version,input_hash
            FROM pending_evaluations
            WHERE pending_id=?
            """,
            (pending_id,),
        ).fetchone()
        expected_pending = (
            snapshot.snapshot_id,
            snapshot.decision_context_snapshot_id,
            str(decision_day),
            int(epoch),
            formula_version,
            snapshot.input_checksum,
        )
        if existing_pending is not None and tuple(existing_pending) != expected_pending:
            raise RuntimeError("serenity_pending_evaluation_immutable_conflict")
        conn.execute(
            """
            INSERT OR IGNORE INTO pending_evaluations(
                pending_id,reference_snapshot_id,decision_context_snapshot_id,decision_day,
                epoch,formula_version,input_hash,status,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                pending_id,
                snapshot.snapshot_id,
                snapshot.decision_context_snapshot_id,
                str(decision_day),
                int(epoch),
                formula_version,
                snapshot.input_checksum,
                "pending",
                created_at,
            ),
        )
    return snapshot.snapshot_id, pending_id


def list_pending_evaluations(*, limit: int = 100) -> List[Dict[str, Any]]:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return []
    try:
        rows = conn.execute(
            "SELECT * FROM pending_evaluations WHERE status='pending' ORDER BY decision_day,pending_id LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def load_pending_evaluation(pending_id: str) -> Dict[str, Any] | None:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        row = conn.execute(
            "SELECT * FROM pending_evaluations WHERE pending_id=?",
            (str(pending_id),),
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def mark_pending_evaluated(pending_id: str, *, evaluated_at: str | None = None) -> None:
    with write_transaction() as conn:
        conn.execute(
            "UPDATE pending_evaluations SET status='evaluated',evaluated_at=? WHERE pending_id=? AND status='pending'",
            (evaluated_at or now_iso(), pending_id),
        )


def save_evaluation(payload: Dict[str, Any]) -> tuple[str, bool]:
    evaluation_id = str(payload.get("evaluation_id") or "")
    if not evaluation_id:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        evaluation_id = "sereval_" + sha256(raw.encode("utf-8")).hexdigest()[:24]
        payload = {**payload, "evaluation_id": evaluation_id}
    with write_transaction() as conn:
        learning_sample_id = str(payload.get("learning_sample_id") or "")
        if learning_sample_id:
            existing = conn.execute(
                "SELECT evaluation_id FROM evaluations WHERE epoch=? AND learning_sample_id=? LIMIT 1",
                (int(payload.get("epoch") or 1), learning_sample_id),
            ).fetchone()
            if existing is not None:
                return str(existing["evaluation_id"]), False
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO evaluations(
                evaluation_id,decision_day,matured_at,epoch,formula_version,input_hash,
                learning_sample_id,payload_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                evaluation_id,
                str(payload.get("decision_day") or ""),
                str(payload.get("matured_at") or ""),
                int(payload.get("epoch") or 1),
                str(payload.get("formula_version") or ""),
                str(payload.get("input_hash") or ""),
                learning_sample_id or None,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                str(payload.get("created_at") or now_iso()),
            ),
        )
        return evaluation_id, cur.rowcount == 1


def commit_evaluation_result(*, payload: Dict[str, Any], pending_id: str) -> tuple[str, bool]:
    evaluation_id = str(payload.get("evaluation_id") or "")
    if not evaluation_id:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        evaluation_id = "sereval_" + sha256(raw.encode("utf-8")).hexdigest()[:24]
        payload = {**payload, "evaluation_id": evaluation_id}
    with write_transaction() as conn:
        learning_sample_id = str(payload.get("learning_sample_id") or "")
        if learning_sample_id:
            existing = conn.execute(
                "SELECT evaluation_id FROM evaluations WHERE epoch=? AND learning_sample_id=? LIMIT 1",
                (int(payload.get("epoch") or 1), learning_sample_id),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    "UPDATE pending_evaluations SET status='evaluated',evaluated_at=? "
                    "WHERE pending_id=? AND status='pending'",
                    (now_iso(), pending_id),
                )
                return str(existing["evaluation_id"]), False
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO evaluations(
                evaluation_id,decision_day,matured_at,epoch,formula_version,input_hash,
                learning_sample_id,payload_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                evaluation_id,
                str(payload.get("decision_day") or ""),
                str(payload.get("matured_at") or ""),
                int(payload.get("epoch") or 1),
                str(payload.get("formula_version") or ""),
                str(payload.get("input_hash") or ""),
                learning_sample_id or None,
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
                str(payload.get("created_at") or now_iso()),
            ),
        )
        conn.execute(
            "UPDATE pending_evaluations SET status='evaluated',evaluated_at=? WHERE pending_id=? AND status='pending'",
            (now_iso(), pending_id),
        )
        return evaluation_id, cur.rowcount == 1


def list_evaluations(*, epoch: int | None = None, limit: int = 1000) -> List[Dict[str, Any]]:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return []
    try:
        where = "" if epoch is None else "WHERE epoch=?"
        params: tuple[Any, ...] = () if epoch is None else (int(epoch),)
        rows = conn.execute(
            f"""
            WITH ranked AS (
                SELECT payload_json,decision_day,created_at,evaluation_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY CASE
                               WHEN COALESCE(learning_sample_id,'')<>'' THEN learning_sample_id
                               ELSE evaluation_id
                           END
                           ORDER BY decision_day DESC,created_at DESC,evaluation_id DESC
                       ) AS sample_rank
                FROM evaluations
                {where}
            )
            SELECT payload_json
            FROM ranked
            WHERE sample_rank=1
            ORDER BY decision_day DESC,created_at DESC,evaluation_id DESC
            LIMIT ?
            """,
            (*params, max(1, int(limit))),
        ).fetchall()
        return [json.loads(row["payload_json"] or "{}") for row in reversed(rows)]
    finally:
        conn.close()


def record_policy_update(*, evaluation_id: str, epoch: int, payload: Dict[str, Any]) -> tuple[str, bool]:
    update_id = "serupd_" + sha256(f"{evaluation_id}|{epoch}|{json.dumps(payload, sort_keys=True, default=str)}".encode()).hexdigest()[:24]
    with write_transaction() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO policy_update_ledger(update_id,evaluation_id,epoch,applied_at,payload_json) VALUES(?,?,?,?,?)",
            (update_id, evaluation_id, int(epoch), now_iso(), json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)),
        )
        return update_id, cur.rowcount == 1


def load_reference_snapshot(snapshot_id: str) -> SerenityReferenceSnapshot | None:
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error):
        return None
    try:
        row = conn.execute("SELECT payload_json FROM reference_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None:
            return None
        return SerenityReferenceSnapshot.model_validate(json.loads(row["payload_json"] or "{}"))
    finally:
        conn.close()


def status_snapshot() -> Dict[str, Any]:
    cfg = load_config().serenity
    base: Dict[str, Any] = {
        "mode": cfg.mode,
        "state": "off" if cfg.mode == "off" else "warming",
        "available": False,
        "applied_weight": 0.0,
        "max_weight": cfg.max_weight,
        "reason": "store_unavailable",
    }
    try:
        conn = _connect(readonly=True)
    except (FileNotFoundError, sqlite3.Error) as ex:
        base["reason"] = f"{type(ex).__name__}: {ex}"
        return base
    try:
        policy = load_policy_state()
        latest_target = conn.execute(
            """
            SELECT t.*,a.activated_at,a.activation_observed_at,
                   a.activation_revision
            FROM active_candidate_target a
            JOIN candidate_targets t ON t.target_id=a.target_id
            WHERE a.singleton=1
            """
        ).fetchone()
        target_id = str(latest_target["target_id"]) if latest_target else None
        target_symbols = (
            {
                str(symbol or "").strip()
                for symbol in json.loads(latest_target["symbols_json"] or "[]")
                if str(symbol or "").strip()
            }
            if latest_target is not None
            else set()
        )
        last = conn.execute(
            "SELECT * FROM poll_runs WHERE source_kind='live' AND (? IS NULL OR target_id=?) ORDER BY finished_at DESC LIMIT 1",
            (target_id, target_id),
        ).fetchone()
        completed = conn.execute(
            "SELECT * FROM poll_runs WHERE source_kind='live' AND complete=1 AND status='success' AND (? IS NULL OR target_id=?) ORDER BY finished_at DESC LIMIT 1",
            (target_id, target_id),
        ).fetchone()
        bootstrap = conn.execute(
            "SELECT * FROM bootstrap_runs WHERE source='cninfo' AND complete=1 ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        breaker = conn.execute("SELECT * FROM source_breakers WHERE source='cninfo'").fetchone()
        heartbeat = conn.execute("SELECT owner_id,heartbeat_at,expires_at FROM worker_lease WHERE lease_name='serenity-worker'").fetchone()
        latest_coverage = (
            conn.execute(
                "SELECT symbol,metadata_complete,hydration_complete,error FROM poll_symbol_coverage WHERE run_id=? ORDER BY symbol",
                (str(last["run_id"]),),
            ).fetchall()
            if last is not None
            else []
        )
        counts = conn.execute(
            "SELECT COUNT(*) AS documents, SUM(CASE WHEN withdrawn=1 THEN 1 ELSE 0 END) AS withdrawn FROM documents"
        ).fetchone()
        unparsed = conn.execute("SELECT COUNT(*) AS n FROM document_versions WHERE extraction_status!='parsed'").fetchone()
        fact_counts = conn.execute(
            """
            SELECT COUNT(*) AS total,
                SUM(CASE WHEN verification_state='verified' THEN 1 ELSE 0 END) AS verified,
                SUM(CASE WHEN verification_state!='verified' THEN 1 ELSE 0 END) AS unverified
            FROM facts
            """
        ).fetchone()
        backfill_count = conn.execute("SELECT COUNT(*) AS n FROM documents WHERE backfill_only=1").fetchone()
        durations = recent_poll_durations("cninfo", limit=cfg.cost_window)
        poll_health = recent_poll_outcomes("cninfo", limit=20)
        recent_complete_rate = (
            sum(
                1
                for row in poll_health
                if bool(row.get("complete"))
                and str(row.get("status") or "") == "success"
            )
            / len(poll_health)
            if poll_health
            else 0.0
        )
        p90 = 0.0
        if durations:
            ordered = sorted(durations)
            p90 = ordered[min(len(ordered) - 1, max(0, int((len(ordered) - 1) * 0.9)))]
        ewma = 0.0
        for value in durations:
            ewma = value if ewma <= 0 else cfg.ewma_alpha * value + (1.0 - cfg.ewma_alpha) * ewma
        completed_at = _parse_iso(completed["finished_at"] if completed else None)
        worker_lease_expires_at = _parse_iso(heartbeat["expires_at"] if heartbeat else None)
        worker_alive = bool(
            heartbeat is not None
            and worker_lease_expires_at is not None
            and worker_lease_expires_at > datetime.now(timezone.utc)
        )
        stale_after_sec = float(completed["stale_after_sec"] or 0.0) if completed else 0.0
        stale = bool(
            completed is not None
            and (
                completed_at is None
                or not math.isfinite(stale_after_sec)
                or stale_after_sec <= 0.0
                or datetime.now(timezone.utc)
                > completed_at + timedelta(seconds=stale_after_sec)
            )
        )
        current_certificate = (
            _target_poll_certificate(
                conn,
                target_id=target_id,
                decision_at=datetime.now(timezone.utc),
            )
            if target_id
            else None
        )
        latest_complete = bool(last["complete"] and str(last["status"]) == "success") if last else False
        target_coverage_complete = bool(
            latest_coverage
            and len(latest_coverage) == len(target_symbols)
            and {str(row["symbol"]) for row in latest_coverage} == target_symbols
            and all(
                bool(row["metadata_complete"]) and bool(row["hydration_complete"])
                for row in latest_coverage
            )
        )
        effective_weight = (
            float(policy.applied_weight)
            if cfg.mode == "native"
            and policy.state in {"probation", "active"}
            and bool(policy.bootstrap_run_id)
            else 0.0
        )
        available = bool(
            cfg.mode == "native"
            and
            bootstrap is not None
            and latest_target is not None
            and current_certificate is not None
            and worker_alive
        )
        if cfg.mode == "off":
            reason = "serenity_mode_off"
        elif not worker_alive:
            reason = "serenity_worker_heartbeat_missing_or_expired"
        elif bootstrap is None:
            reason = "real_bootstrap_incomplete"
        elif latest_target is None:
            reason = "candidate_target_unavailable"
        elif last is None:
            reason = "no_official_poll"
        elif not latest_complete:
            reason = "latest_poll_incomplete"
        elif not target_coverage_complete:
            reason = "target_coverage_incomplete"
        elif stale:
            reason = "official_source_stale"
        elif current_certificate is None:
            reason = "active_target_poll_certificate_missing"
        else:
            reason = None
        return {
            **base,
            "available": available,
            "bootstrap_ready": bootstrap is not None,
            "bootstrap_run_id": (bootstrap["bootstrap_id"] if bootstrap else None),
            "stale": stale,
            "state": "off" if cfg.mode == "off" else policy.state,
            "policy_state": policy.state,
            "applied_weight": effective_weight,
            "stored_applied_weight": float(policy.applied_weight),
            "epoch": policy.epoch,
            "matured_days": policy.matured_days,
            "available_results": policy.available_results,
            "last_evaluation_at": policy.last_evaluation_at,
            "suspension_reasons": list(policy.suspension_reasons),
            "last_poll_at": (last["finished_at"] if last else None),
            "last_complete_poll_at": (completed["finished_at"] if completed else None),
            "next_due_at": (last["next_due_at"] if last else None),
            "last_elapsed_sec": (float(last["elapsed_sec"]) if last else None),
            "ewma_elapsed_sec": round(ewma, 3),
            "p90_elapsed_sec": round(p90, 3),
            "last_poll_status": (last["status"] if last else None),
            "last_poll_complete": bool(last["complete"]) if last else False,
            "source_health": {
                "recent_complete_rate": recent_complete_rate,
                "poll_count": len(poll_health),
                "policy_recorded": dict(policy.source_health or {}),
                "verified_fact_count": int(fact_counts["verified"] or 0),
                "unverified_fact_count": int(fact_counts["unverified"] or 0),
                "backfill_document_count": int(backfill_count["n"] or 0),
                "target_count": len(latest_coverage),
                "target_incomplete_count": sum(
                    1
                    for row in latest_coverage
                    if not bool(row["metadata_complete"])
                    or not bool(row["hydration_complete"])
                ),
                "target_errors": [
                    {"symbol": str(row["symbol"]), "error": str(row["error"] or "")[:160]}
                    for row in latest_coverage
                    if row["error"]
                ][:10],
            },
            "candidate_target": (
                {
                    "target_id": str(latest_target["target_id"]),
                    "decision_trade_day": str(latest_target["decision_trade_day"]),
                    "daybook_effective_day": str(latest_target["daybook_effective_day"]),
                    "observed_at": str(latest_target["observed_at"]),
                    "symbols": list(json.loads(latest_target["symbols_json"] or "[]")),
                    "input_hash": str(latest_target["input_hash"]),
                    "activated_at": str(latest_target["activated_at"]),
                    "activation_observed_at": str(
                        latest_target["activation_observed_at"] or ""
                    ),
                    "activation_revision": str(
                        latest_target["activation_revision"] or ""
                    ),
                }
                if latest_target is not None
                else None
            ),
            "worker_heartbeat_at": (heartbeat["heartbeat_at"] if heartbeat else None),
            "worker_lease_expires_at": (heartbeat["expires_at"] if heartbeat else None),
            "worker_alive": worker_alive,
            "document_count": int(counts["documents"] or 0),
            "withdrawn_count": int(counts["withdrawn"] or 0),
            "unparsed_count": int(unparsed["n"] or 0),
            "breaker": dict(breaker) if breaker else {},
            "reason": reason,
        }
    except Exception as ex:  # noqa: BLE001
        return {**base, "reason": f"{type(ex).__name__}: {ex}"}
    finally:
        conn.close()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
