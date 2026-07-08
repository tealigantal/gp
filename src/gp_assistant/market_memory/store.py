from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.paths import store_dir
from ..runtime.utils import now_iso

_SCHEMA_LOCK = threading.Lock()
_DB_LOCK = threading.RLock()
_DB_STATE = threading.local()
_SCHEMA_READY: set[str] = set()


@dataclass
class MarketMemoryEvent:
    event_id: str
    as_of: str
    symbol: str
    signal_type: str
    feature_vector: Dict[str, float]
    features: Dict[str, Any]
    market_context: Dict[str, Any]
    outcome: Dict[str, Any]
    data_provenance: Dict[str, Any]


def _db_path() -> Path:
    return _event_root() / "market_memory.db"


def _lock_path() -> Path:
    return _event_root() / ".market_memory.lock"


def _snapshot_dir() -> Path:
    path = _event_root() / "decision_snapshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _event_root() -> Path:
    path = Path(os.getenv("GP_MARKET_MEMORY_DIR") or str(store_dir() / "events"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def decision_snapshot_path(snapshot_id: str) -> Path:
    return _snapshot_dir() / f"{snapshot_id}.json"


def _acquire_process_lock(path: Path, *, timeout_sec: float = 30.0) -> None:
    deadline = time.monotonic() + timeout_sec
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()} {time.time():.6f}\n".encode("utf-8"))
            finally:
                os.close(fd)
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for market memory lock: {path}")
            time.sleep(0.05)


def _release_process_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


@contextmanager
def memory_db_lane():
    path = _lock_path()
    _DB_LOCK.acquire()
    depth = int(getattr(_DB_STATE, "depth", 0) or 0)
    outermost = depth == 0
    try:
        if outermost:
            _acquire_process_lock(path)
        _DB_STATE.depth = depth + 1
        yield
    finally:
        _DB_STATE.depth = max(int(getattr(_DB_STATE, "depth", 1) or 1) - 1, 0)
        if outermost:
            _release_process_lock(path)
        _DB_LOCK.release()


def _connect() -> sqlite3.Connection:
    dbp = str(_db_path())
    conn = sqlite3.connect(dbp, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass
    if dbp not in _SCHEMA_READY:
        with _SCHEMA_LOCK:
            if dbp not in _SCHEMA_READY:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS market_events(
                        event_id TEXT PRIMARY KEY,
                        as_of TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        signal_type TEXT NOT NULL,
                        feature_vector_json TEXT NOT NULL,
                        features_json TEXT NOT NULL,
                        market_context_json TEXT NOT NULL,
                        outcome_json TEXT NOT NULL,
                        data_provenance_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_market_events_asof ON market_events(as_of)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_market_events_symbol ON market_events(symbol)")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS decision_snapshots(
                        snapshot_id TEXT PRIMARY KEY,
                        run_id TEXT,
                        as_of TEXT NOT NULL,
                        final_decision TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS prediction_outcomes(
                        outcome_id TEXT PRIMARY KEY,
                        snapshot_id TEXT NOT NULL,
                        symbol TEXT,
                        role TEXT NOT NULL,
                        as_of TEXT NOT NULL,
                        outcome_json TEXT NOT NULL,
                        error_types_json TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
                _SCHEMA_READY.add(dbp)
    return conn


def _event_id(symbol: str, as_of: str, signal_type: str, feature_vector: Dict[str, Any]) -> str:
    rounded = {key: round(float(value), 6) for key, value in sorted(feature_vector.items())}
    raw = json.dumps(
        {"symbol": symbol, "as_of": as_of, "signal_type": signal_type, "vector": rounded},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "mme_" + sha256(raw.encode("utf-8")).hexdigest()[:24]


def make_market_event(
    *,
    as_of: str,
    symbol: str,
    signal_type: str,
    feature_vector: Dict[str, float],
    features: Dict[str, Any],
    market_context: Dict[str, Any],
    outcome: Dict[str, Any],
    data_provenance: Dict[str, Any],
) -> MarketMemoryEvent:
    return MarketMemoryEvent(
        event_id=_event_id(symbol, as_of, signal_type, feature_vector),
        as_of=as_of,
        symbol=symbol,
        signal_type=signal_type,
        feature_vector=feature_vector,
        features=features,
        market_context=market_context,
        outcome=outcome,
        data_provenance=data_provenance,
    )


def upsert_market_event(event: MarketMemoryEvent) -> str:
    with memory_db_lane():
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO market_events(
                    event_id, as_of, symbol, signal_type, feature_vector_json, features_json,
                    market_context_json, outcome_json, data_provenance_json, created_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET
                    feature_vector_json=excluded.feature_vector_json,
                    features_json=excluded.features_json,
                    market_context_json=excluded.market_context_json,
                    outcome_json=excluded.outcome_json,
                    data_provenance_json=excluded.data_provenance_json
                """,
                (
                    event.event_id,
                    event.as_of,
                    event.symbol,
                    event.signal_type,
                    json.dumps(event.feature_vector, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.features, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.market_context, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.outcome, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.data_provenance, ensure_ascii=False, sort_keys=True),
                    now_iso(),
                ),
            )
            conn.commit()
            return event.event_id
        finally:
            conn.close()


def upsert_market_events(events: Iterable[MarketMemoryEvent]) -> int:
    count = 0
    for event in events:
        upsert_market_event(event)
        count += 1
    return count


def _row_to_event(row: sqlite3.Row) -> MarketMemoryEvent:
    return MarketMemoryEvent(
        event_id=str(row["event_id"]),
        as_of=str(row["as_of"]),
        symbol=str(row["symbol"]),
        signal_type=str(row["signal_type"]),
        feature_vector=json.loads(row["feature_vector_json"] or "{}"),
        features=json.loads(row["features_json"] or "{}"),
        market_context=json.loads(row["market_context_json"] or "{}"),
        outcome=json.loads(row["outcome_json"] or "{}"),
        data_provenance=json.loads(row["data_provenance_json"] or "{}"),
    )


def list_events_before(as_of: str, *, require_outcome: bool = True, limit: Optional[int] = None) -> List[MarketMemoryEvent]:
    with memory_db_lane():
        conn = _connect()
        try:
            sql = "SELECT * FROM market_events WHERE as_of < ? ORDER BY as_of DESC"
            params: list[Any] = [as_of]
            if limit is not None:
                sql += " LIMIT ?"
                params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            out = [_row_to_event(row) for row in rows]
            if require_outcome:
                out = [event for event in out if bool((event.outcome or {}).get("complete") is True)]
            return out
        finally:
            conn.close()


def save_decision_snapshot(snapshot: Dict[str, Any]) -> str:
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    if not snapshot_id:
        raw = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
        snapshot_id = "dcs_" + sha256(raw.encode("utf-8")).hexdigest()[:24]
        snapshot["snapshot_id"] = snapshot_id
    path = decision_snapshot_path(snapshot_id)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True, default=str), encoding="utf-8")
    with memory_db_lane():
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO decision_snapshots(snapshot_id, run_id, as_of, final_decision, payload_json, created_at)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(snapshot_id) DO UPDATE SET
                    run_id=excluded.run_id,
                    final_decision=excluded.final_decision,
                    payload_json=excluded.payload_json
                """,
                (
                    snapshot_id,
                    snapshot.get("run_id"),
                    str(snapshot.get("as_of") or ""),
                    str(snapshot.get("final_decision") or snapshot.get("decision") or "unknown"),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str),
                    now_iso(),
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return snapshot_id


def load_decision_snapshot(snapshot_id: str) -> Dict[str, Any] | None:
    path = decision_snapshot_path(snapshot_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    with memory_db_lane():
        conn = _connect()
        try:
            row = conn.execute("SELECT payload_json FROM decision_snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
            if row is None:
                return None
            return json.loads(row["payload_json"] or "{}")
        finally:
            conn.close()


def save_prediction_outcome(
    *,
    snapshot_id: str,
    symbol: str | None,
    role: str,
    as_of: str,
    outcome: Dict[str, Any],
    error_types: List[str],
) -> str:
    raw = json.dumps(
        {"snapshot_id": snapshot_id, "symbol": symbol, "role": role, "as_of": as_of},
        ensure_ascii=False,
        sort_keys=True,
    )
    outcome_id = "po_" + sha256(raw.encode("utf-8")).hexdigest()[:24]
    with memory_db_lane():
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO prediction_outcomes(
                    outcome_id, snapshot_id, symbol, role, as_of, outcome_json, error_types_json, created_at
                )
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(outcome_id) DO UPDATE SET
                    outcome_json=excluded.outcome_json,
                    error_types_json=excluded.error_types_json
                """,
                (
                    outcome_id,
                    snapshot_id,
                    symbol,
                    role,
                    as_of,
                    json.dumps(outcome, ensure_ascii=False, sort_keys=True),
                    json.dumps(error_types, ensure_ascii=False),
                    now_iso(),
                ),
            )
            conn.commit()
            return outcome_id
        finally:
            conn.close()
