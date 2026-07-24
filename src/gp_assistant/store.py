from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from typing import Iterator

from .contracts.conversation import ConversationSession, ConversationTurn
from .contracts.decision import RecommendationPlan
from .contracts.publication import RecommendationPublication
from .contracts.runtime import RuntimeObservation


DATABASE_SCHEMA = "contract_kernel.v1"


class ContractStoreError(RuntimeError):
    pass


class UnsupportedDatabaseSchema(ContractStoreError):
    pass


class PublicationConflict(ContractStoreError):
    pass


def contract_database_path() -> Path:
    return Path(os.getenv("GP_CONTRACT_DB") or os.getenv("GP_AGENT_DB") or "store/agent.db")


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class ContractStore:
    """The sole runtime persistence boundary for canonical recommendation contracts."""

    def __init__(self, path: Path | None = None):
        self.path = path or contract_database_path()

    def _connect(self, *, writable: bool) -> sqlite3.Connection:
        if writable:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        else:
            conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def initialize(self) -> None:
        existed = self.path.exists()
        conn = self._connect(writable=True)
        try:
            names = {str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if existed and names and "schema_metadata" not in names:
                raise UnsupportedDatabaseSchema("unsupported_database_schema")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS schema_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = conn.execute("SELECT value FROM schema_metadata WHERE key='schema'").fetchone()
            if row is None:
                conn.execute("INSERT INTO schema_metadata(key,value) VALUES('schema',?)", (DATABASE_SCHEMA,))
            elif str(row["value"]) != DATABASE_SCHEMA:
                raise UnsupportedDatabaseSchema("unsupported_database_schema")
            for statement in (
                "CREATE TABLE IF NOT EXISTS recommendation_plans(plan_id TEXT PRIMARY KEY, lookup_digest TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL UNIQUE, generated_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS runtime_observations(runtime_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES recommendation_plans(plan_id), payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL UNIQUE, observed_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS recommendation_publications(publication_id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES recommendation_plans(plan_id), runtime_id TEXT REFERENCES runtime_observations(runtime_id), payload_json TEXT NOT NULL, payload_digest TEXT NOT NULL UNIQUE, published_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS current_publication(singleton INTEGER PRIMARY KEY CHECK(singleton=1), publication_id TEXT NOT NULL REFERENCES recommendation_publications(publication_id))",
                "CREATE TABLE IF NOT EXISTS sessions(session_id TEXT PRIMARY KEY, active_publication_id TEXT NOT NULL REFERENCES recommendation_publications(publication_id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS deleted_sessions(session_id TEXT PRIMARY KEY, deleted_at TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS turns(turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE, publication_id TEXT NOT NULL REFERENCES recommendation_publications(publication_id), sequence INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created_at TEXT NOT NULL, client_turn_id TEXT, UNIQUE(session_id,sequence))",
                "CREATE TABLE IF NOT EXISTS claims(claim_id TEXT PRIMARY KEY, turn_id TEXT NOT NULL REFERENCES turns(turn_id) ON DELETE CASCADE, subject TEXT NOT NULL, predicate TEXT NOT NULL, value_json TEXT NOT NULL, created_at TEXT NOT NULL)",
            ):
                conn.execute(statement)
            columns = {str(row["name"]) for row in conn.execute("PRAGMA table_info(turns)")}
            if "client_turn_id" not in columns:
                conn.execute("ALTER TABLE turns ADD COLUMN client_turn_id TEXT")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_turns_client_role ON turns(session_id,client_turn_id,role) WHERE client_turn_id IS NOT NULL")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        conn = self._connect(writable=True)
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

    @staticmethod
    def _encode(model: RecommendationPlan | RuntimeObservation | RecommendationPublication | ConversationSession | ConversationTurn) -> tuple[str, str]:
        payload = model.model_dump(mode="json")
        return _canonical_json(payload), _digest(payload)

    def load_exact_plan(self, lookup_digest: str) -> RecommendationPlan | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute("SELECT payload_json FROM recommendation_plans WHERE lookup_digest=?", (lookup_digest,)).fetchone()
            return RecommendationPlan.model_validate_json(str(row["payload_json"])) if row else None
        finally:
            conn.close()

    def load_plan(self, plan_id: str) -> RecommendationPlan | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute("SELECT payload_json FROM recommendation_plans WHERE plan_id=?", (plan_id,)).fetchone()
            return RecommendationPlan.model_validate_json(str(row["payload_json"])) if row else None
        finally:
            conn.close()

    def commit_plan(self, plan: RecommendationPlan) -> None:
        encoded, payload_digest = self._encode(plan)
        lookup_digest = _digest(plan.lookup_key.model_dump(mode="json"))
        with self._transaction() as conn:
            existing = conn.execute("SELECT payload_digest FROM recommendation_plans WHERE plan_id=?", (plan.plan_id,)).fetchone()
            if existing and str(existing["payload_digest"]) != payload_digest:
                raise PublicationConflict("plan_identity_conflict")
            conn.execute("INSERT OR IGNORE INTO recommendation_plans(plan_id,lookup_digest,payload_json,payload_digest,generated_at) VALUES(?,?,?,?,?)", (plan.plan_id, lookup_digest, encoded, payload_digest, plan.generated_at.isoformat()))

    def commit_runtime(self, runtime: RuntimeObservation) -> None:
        if self.load_plan(runtime.plan_id) is None:
            raise ContractStoreError("plan_not_found")
        encoded, payload_digest = self._encode(runtime)
        with self._transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO runtime_observations(runtime_id,plan_id,payload_json,payload_digest,observed_at) VALUES(?,?,?,?,?)", (runtime.runtime_id, runtime.plan_id, encoded, payload_digest, runtime.observed_at.isoformat()))

    def load_runtime(self, runtime_id: str) -> RuntimeObservation | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute("SELECT payload_json FROM runtime_observations WHERE runtime_id=?", (runtime_id,)).fetchone()
            return RuntimeObservation.model_validate_json(str(row["payload_json"])) if row else None
        finally:
            conn.close()

    def commit_publication(self, publication: RecommendationPublication) -> None:
        if self.load_plan(publication.plan_id) is None:
            raise ContractStoreError("plan_not_found")
        if publication.runtime_id and self.load_runtime(publication.runtime_id) is None:
            raise ContractStoreError("runtime_plan_mismatch")
        encoded, payload_digest = self._encode(publication)
        with self._transaction() as conn:
            conn.execute("INSERT OR IGNORE INTO recommendation_publications(publication_id,plan_id,runtime_id,payload_json,payload_digest,published_at) VALUES(?,?,?,?,?,?)", (publication.publication_id, publication.plan_id, publication.runtime_id, encoded, payload_digest, publication.published_at.isoformat()))
            conn.execute("INSERT INTO current_publication(singleton,publication_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET publication_id=excluded.publication_id", (publication.publication_id,))

    def current_publication(self) -> RecommendationPublication | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute("SELECT p.payload_json FROM current_publication c JOIN recommendation_publications p ON p.publication_id=c.publication_id WHERE c.singleton=1").fetchone()
            return RecommendationPublication.model_validate_json(str(row["payload_json"])) if row else None
        finally:
            conn.close()

    def create_session(self, session: ConversationSession) -> None:
        self._require_publication(session.active_publication_id)
        with self._transaction() as conn:
            conn.execute("INSERT INTO sessions(session_id,active_publication_id,created_at,updated_at) VALUES(?,?,?,?)", (session.session_id, session.active_publication_id, session.created_at.isoformat(), session.updated_at.isoformat()))

    def append_turn(self, turn: ConversationTurn) -> None:
        self._require_publication(turn.publication_id)
        with self._transaction() as conn:
            conn.execute("INSERT INTO turns(turn_id,session_id,publication_id,sequence,role,content,created_at,client_turn_id) VALUES(?,?,?,?,?,?,?,?)", (turn.turn_id, turn.session_id, turn.publication_id, turn.sequence, turn.role, turn.content, turn.created_at.isoformat(), turn.client_turn_id))

    def session_publication(self, session_id: str) -> RecommendationPublication | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute("SELECT active_publication_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            return self.load_publication(str(row["active_publication_id"])) if row else None
        finally:
            conn.close()

    def list_conversation_sessions(self, *, limit: int = 20) -> list[ConversationSession]:
        if not self.path.exists():
            return []
        self.initialize()
        conn = self._connect(writable=False)
        try:
            rows = conn.execute(
                "SELECT session_id,active_publication_id,created_at,updated_at FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
            return [ConversationSession.model_validate(dict(row)) for row in rows]
        finally:
            conn.close()

    def read_conversation_session(self, session_id: str) -> tuple[ConversationSession, list[ConversationTurn]] | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute(
                "SELECT session_id,active_publication_id,created_at,updated_at FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            turns = conn.execute(
                "SELECT turn_id,session_id,publication_id,sequence,role,content,created_at,client_turn_id FROM turns WHERE session_id=? ORDER BY sequence ASC",
                (session_id,),
            ).fetchall()
            return ConversationSession.model_validate(dict(row)), [ConversationTurn.model_validate(dict(turn)) for turn in turns]
        finally:
            conn.close()

    def delete_conversation_session(self, session_id: str) -> bool:
        """Delete exactly one conversation and its cascaded turns and claims."""
        if not self.path.exists():
            return False
        with self._transaction() as conn:
            exists = conn.execute("SELECT 1 FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if exists is None:
                return False
            conn.execute("INSERT OR IGNORE INTO deleted_sessions(session_id,deleted_at) VALUES(?,?)", (session_id, datetime.now(UTC).isoformat()))
            cursor = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            return cursor.rowcount == 1

    def prepare_conversation(self, *, session_id: str, publication_id: str, now: datetime) -> RecommendationPublication:
        """Create a session once; an existing session remains bound to its publication."""
        with self._transaction() as conn:
            deleted = conn.execute("SELECT 1 FROM deleted_sessions WHERE session_id=?", (session_id,)).fetchone()
            if deleted is not None:
                raise ContractStoreError("conversation_deleted")
            row = conn.execute("SELECT active_publication_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO sessions(session_id,active_publication_id,created_at,updated_at) VALUES(?,?,?,?)", (session_id, publication_id, now.isoformat(), now.isoformat()))
                resolved_id = publication_id
            else:
                resolved_id = str(row["active_publication_id"])
        publication = self.load_publication(resolved_id)
        if publication is None:
            raise ContractStoreError("publication_not_found")
        return publication

    def existing_reply(self, *, session_id: str, client_turn_id: str) -> str | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute("SELECT content FROM turns WHERE session_id=? AND client_turn_id=? AND role='assistant'", (session_id, client_turn_id)).fetchone()
            return str(row["content"]) if row else None
        finally:
            conn.close()

    def commit_conversation_exchange(self, *, session_id: str, publication_id: str, client_turn_id: str, user_turn_id: str, user_message: str, assistant_turn_id: str, assistant_message: str, now: datetime) -> str:
        """Persist a client turn and its reply atomically, returning a prior reply on retry."""
        with self._transaction() as conn:
            existing = conn.execute("SELECT content FROM turns WHERE session_id=? AND client_turn_id=? AND role='assistant'", (session_id, client_turn_id)).fetchone()
            if existing is not None:
                return str(existing["content"])
            session = conn.execute("SELECT active_publication_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
            if session is None or str(session["active_publication_id"]) != publication_id:
                raise ContractStoreError("session_publication_mismatch")
            row = conn.execute("SELECT COALESCE(MAX(sequence),0) AS maximum FROM turns WHERE session_id=?", (session_id,)).fetchone()
            first_sequence = int(row["maximum"]) + 1
            conn.execute("INSERT INTO turns(turn_id,session_id,publication_id,sequence,role,content,created_at,client_turn_id) VALUES(?,?,?,?,?,?,?,?)", (user_turn_id, session_id, publication_id, first_sequence, "user", user_message, now.isoformat(), client_turn_id))
            conn.execute("INSERT INTO turns(turn_id,session_id,publication_id,sequence,role,content,created_at,client_turn_id) VALUES(?,?,?,?,?,?,?,?)", (assistant_turn_id, session_id, publication_id, first_sequence + 1, "assistant", assistant_message, now.isoformat(), client_turn_id))
            conn.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (now.isoformat(), session_id))
            return assistant_message

    def _require_publication(self, publication_id: str) -> None:
        if self.load_publication(publication_id) is None:
            raise ContractStoreError("publication_not_found")

    def load_publication(self, publication_id: str) -> RecommendationPublication | None:
        if not self.path.exists():
            return None
        self.initialize()
        conn = self._connect(writable=False)
        try:
            row = conn.execute("SELECT payload_json FROM recommendation_publications WHERE publication_id=?", (publication_id,)).fetchone()
            return RecommendationPublication.model_validate_json(str(row["payload_json"])) if row else None
        finally:
            conn.close()

    def health(self) -> dict[str, object]:
        publication = self.current_publication()
        plan = self.load_plan(publication.plan_id) if publication else None
        runtime = self.load_runtime(publication.runtime_id) if publication and publication.runtime_id else None
        daily_state = "unavailable"
        if plan is not None:
            daily_state = "pending" if "daily_evidence_pending" in plan.decision.reason_codes else "ready"
        from .serenity.service import status_snapshot as serenity_status

        raw_serenity = serenity_status()
        public_serenity = {
            "mode": raw_serenity.get("mode"),
            "state": raw_serenity.get("state"),
            "target_ready": bool(raw_serenity.get("target_ready")),
            "batch_ready": bool(raw_serenity.get("batch_ready")),
        }

        return {
            "current_publication_id": publication.publication_id if publication else None,
            "plan_id": publication.plan_id if publication else None,
            "runtime_id": publication.runtime_id if publication else None,
            "market_session_date": plan.market_session_date.isoformat() if plan else None,
            "daily_evidence_date": plan.daily_evidence_date.isoformat() if plan and plan.daily_evidence_date else None,
            "slot_closed_at": runtime.slot_closed_at.isoformat() if runtime and runtime.slot_closed_at else None,
            "market_phase": runtime.market_phase.value if runtime else None,
            "daily_data_state": daily_state,
            "runtime_data_state": runtime.data_quality.state.value if runtime else "unavailable",
            "publication_state": publication.decision.plan_status.value if publication else "unavailable",
            "tradeability_state": "tradeable" if publication and publication.decision.tradeable_now else "unavailable",
            "serenity": public_serenity,
        }
