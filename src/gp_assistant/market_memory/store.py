from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..core.paths import store_dir
def iso_day(value: object) -> str:
    return str(value or "").replace("/", "-")[:10]
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
    signal_trading_day: str | None = None
    outcome_available_trading_day: str | None = None
    outcome_complete: bool = False
    first_seen_at: str | None = None


def _db_path() -> Path:
    return _event_root() / "market_memory.db"


def _lock_path() -> Path:
    return _event_root() / ".market_memory.lock"


def _event_root() -> Path:
    path = Path(os.getenv("GP_MARKET_MEMORY_DIR") or str(store_dir() / "events"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _acquire_process_lock(path: Path, *, timeout_sec: float = 1.2) -> str:
    deadline = time.monotonic() + timeout_sec
    token = uuid.uuid4().hex
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()} {time.time():.6f} {token}\n".encode("utf-8"))
            finally:
                os.close(fd)
            return token
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for market memory lock: {path}")
            time.sleep(0.05)


def _release_process_lock(path: Path, token: str) -> None:
    try:
        if token in path.read_text(encoding="utf-8"):
            path.unlink()
    except FileNotFoundError:
        return


@contextmanager
def memory_db_lane():
    path = _lock_path()
    _DB_LOCK.acquire()
    depth = int(getattr(_DB_STATE, "depth", 0) or 0)
    outermost = depth == 0
    token: str | None = None
    try:
        if outermost:
            token = _acquire_process_lock(path)
        _DB_STATE.depth = depth + 1
        yield
    finally:
        _DB_STATE.depth = max(int(getattr(_DB_STATE, "depth", 1) or 1) - 1, 0)
        if outermost and token is not None:
            _release_process_lock(path, token)
        _DB_LOCK.release()


def _connect(*, writable: bool = False) -> sqlite3.Connection | None:
    path = _db_path()
    dbp = str(path)
    if not writable and not path.exists():
        return None
    if writable:
        conn = sqlite3.connect(dbp, timeout=1.2)
    else:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=0.5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=1200" if writable else "PRAGMA busy_timeout=500")
    if not writable:
        conn.execute("PRAGMA query_only=ON")
        return conn
    conn.execute("PRAGMA journal_mode=DELETE")
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
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(market_events)").fetchall()}
                for name, definition in (
                    ("signal_trading_day", "TEXT"),
                    ("outcome_available_trading_day", "TEXT"),
                    ("outcome_complete", "INTEGER NOT NULL DEFAULT 0"),
                    ("first_seen_at", "TEXT"),
                ):
                    if name not in columns:
                        conn.execute(f"ALTER TABLE market_events ADD COLUMN {name} {definition}")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_market_events_maturity ON market_events(signal_trading_day,outcome_available_trading_day,outcome_complete)")
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
    signal_day = iso_day(str(data_provenance.get("signal_trading_day") or as_of))
    outcome_day = outcome.get("outcome_available_trading_day") or data_provenance.get("outcome_available_trading_day")
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
        signal_trading_day=signal_day,
        outcome_available_trading_day=iso_day(str(outcome_day)) if outcome_day else None,
        outcome_complete=bool(outcome.get("complete") is True),
        first_seen_at=now_iso(),
    )


def upsert_market_event(event: MarketMemoryEvent) -> str:
    upsert_market_events([event])
    return event.event_id


def upsert_market_events(events: Iterable[MarketMemoryEvent]) -> int:
    rows = list(events)
    if not rows:
        return 0
    for event in rows:
        signal_day = iso_day(event.signal_trading_day)
        available_day = iso_day(event.outcome_available_trading_day)
        if signal_day is None or (event.outcome_complete and (available_day is None or available_day <= signal_day)):
            raise ValueError("market_memory_date_contract_invalid")
        if not str(event.first_seen_at or "").strip() or "+" not in str(event.first_seen_at) and "Z" not in str(event.first_seen_at):
            raise ValueError("market_memory_first_seen_timezone_required")
    with memory_db_lane():
        conn = _connect(writable=True)
        assert conn is not None
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany(
                """
                INSERT INTO market_events(
                    event_id,as_of,symbol,signal_type,feature_vector_json,features_json,market_context_json,outcome_json,
                    data_provenance_json,created_at,signal_trading_day,outcome_available_trading_day,outcome_complete,first_seen_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING
                """,
                [(
                    event.event_id, event.as_of, event.symbol, event.signal_type,
                    json.dumps(event.feature_vector, ensure_ascii=False, sort_keys=True), json.dumps(event.features, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.market_context, ensure_ascii=False, sort_keys=True), json.dumps(event.outcome, ensure_ascii=False, sort_keys=True),
                    json.dumps(event.data_provenance, ensure_ascii=False, sort_keys=True), now_iso(), event.signal_trading_day,
                    event.outcome_available_trading_day, int(event.outcome_complete), event.first_seen_at or now_iso(),
                ) for event in rows],
            )
            conn.execute("COMMIT")
            return len(rows)
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()


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
        signal_trading_day=row["signal_trading_day"],
        outcome_available_trading_day=row["outcome_available_trading_day"],
        outcome_complete=bool(row["outcome_complete"]),
        first_seen_at=row["first_seen_at"],
    )


def list_events_before(as_of: str, *, require_outcome: bool = True, limit: Optional[int] = None) -> List[MarketMemoryEvent]:
    conn = _connect()
    if conn is None:
        return []
    try:
        cutoff = iso_day(as_of) or as_of
        sql = "SELECT * FROM market_events WHERE signal_trading_day < ?"
        params: list[Any] = [cutoff]
        if require_outcome:
            sql += " AND outcome_complete=1 AND outcome_available_trading_day IS NOT NULL AND outcome_available_trading_day < ?"
            params.append(cutoff)
        sql += " ORDER BY signal_trading_day DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [_row_to_event(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
