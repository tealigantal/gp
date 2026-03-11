from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ..core.config import load_config
from ..core.paths import store_dir

_WRITE_LOCK = threading.RLock()

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_INIT_PATHS: set[str] = set()
_ENSURED_QUERIES: set[tuple[str, str]] = set()


def _db_path() -> Path:
    p = store_dir() / "search" / "history.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    dbp = str(_db_path())
    conn = sqlite3.connect(dbp, timeout=15.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass

    # Schema init per database path (important for tests that monkeypatch GP_STORE_DIR)
    if dbp not in _SCHEMA_INIT_PATHS:
        with _SCHEMA_LOCK:
            if dbp not in _SCHEMA_INIT_PATHS:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS queries(
                        id TEXT PRIMARY KEY,
                        params TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        last_fetch_at TEXT,
                        last_item_time TEXT
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS items(
                        query_id TEXT,
                        item_id TEXT,
                        item_time TEXT,
                        etag TEXT,
                        payload TEXT,
                        updated_at TEXT,
                        PRIMARY KEY (query_id, item_id)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_items_query_time ON items(query_id, item_time)"
                )
                conn.commit()
                _SCHEMA_INIT_PATHS.add(dbp)
    return conn


def _retry_on_locked(fn: Callable[[], Any], *, retries: int = 8, base_delay: float = 0.08):
    for i in range(max(1, retries)):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "database is locked" in msg or "database is busy" in msg:
                time.sleep(base_delay * (2 ** i))
                continue
            raise
    return fn()


def _now_iso() -> str:
    cfg = load_config()
    tz = timezone.utc
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(cfg.timezone)
    except Exception:
        pass
    return datetime.now(tz=tz).isoformat()


def canonical_query_id(params: Dict[str, Any]) -> str:
    """Stable, compact id for a query's normalized params.

    Serialize with sorted keys and hash; keep short prefix for readability.
    """
    norm = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(norm.encode("utf-8")).hexdigest()[:16]


def ensure_query(query_id: str, params: Dict[str, Any]) -> None:
    # Cache must be scoped by DB path, otherwise tests / alternate GP_STORE_DIR
    # may reuse an ensured query_id from a different sqlite file.
    key = (str(_db_path()), query_id)
    if key in _ENSURED_QUERIES:
        return

    pjson = json.dumps(params, ensure_ascii=False, sort_keys=True)
    with _WRITE_LOCK:
        if key in _ENSURED_QUERIES:
            return
        conn = _connect()
        try:
            def _write() -> None:
                cur = conn.execute("SELECT id FROM queries WHERE id=?", (query_id,))
                row = cur.fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO queries(id, params, created_at, updated_at) VALUES (?,?,?,?)",
                        (query_id, pjson, _now_iso(), _now_iso()),
                    )
                else:
                    conn.execute(
                        "UPDATE queries SET params=?, updated_at=? WHERE id=?",
                        (pjson, _now_iso(), query_id),
                    )
                conn.commit()

            _retry_on_locked(_write)
            _ENSURED_QUERIES.add(key)
        finally:
            conn.close()


def query_meta(query_id: str) -> Dict[str, Any]:
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT id, params, created_at, updated_at, last_fetch_at, last_item_time FROM queries WHERE id=?",
            (query_id,),
        )
        r = cur.fetchone()
        if r is None:
            return {
                "id": query_id,
                "params": None,
                "created_at": None,
                "updated_at": None,
                "last_fetch_at": None,
                "last_item_time": None,
            }
        return {
            "id": r[0],
            "params": json.loads(r[1]) if r[1] else None,
            "created_at": r[2],
            "updated_at": r[3],
            "last_fetch_at": r[4],
            "last_item_time": r[5],
        }
    finally:
        conn.close()


def count_items(query_id: str, *, since: Optional[str] = None) -> int:
    conn = _connect()
    try:
        if since is None:
            cur = conn.execute("SELECT COUNT(*) FROM items WHERE query_id=?", (query_id,))
        else:
            cur = conn.execute(
                "SELECT COUNT(*) FROM items WHERE query_id=? AND (item_time >= ?)",
                (query_id, since),
            )
        r = cur.fetchone()
        return int(r[0] or 0) if r else 0
    finally:
        conn.close()


def watermark(query_id: str) -> Optional[str]:
    meta = query_meta(query_id)
    return meta.get("last_item_time")


def _iso_to_dt(s: str) -> datetime:
    # Fallback parse for simple YYYY-MM-DD strings
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def compute_next_range(
    query_id: str,
    *,
    user_start: Optional[str] = None,
    user_end: Optional[str] = None,
    safety_lookback_days: int = 2,
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve [start, end] for incremental fetch.

    - If user_start provided: use max(user_start, wm - safety).
    - Else: start from wm - safety if wm exists, else None (full load).
    - End uses user_end unchanged.
    Returns ISO strings or None.
    """
    wm = watermark(query_id)
    if wm is None:
        return user_start, user_end
    try:
        base = _iso_to_dt(wm) - timedelta(days=max(0, int(safety_lookback_days)))
        resolved_start = base.isoformat()
        if user_start is not None:
            s = _iso_to_dt(user_start)
            if s > base:
                resolved_start = user_start
        return resolved_start, user_end
    except Exception:
        return user_start, user_end


def upsert_items(
    query_id: str,
    items: Iterable[Dict[str, Any]],
    *,
    id_key: str = "id",
    time_key: str = "time",
    etag_key: Optional[str] = None,
    payload_mapper: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Insert or update items for a query and advance watermark.

    - items: iterable of dicts
    - id_key: key for unique id per item
    - time_key: key for event/update time per item (ISO preferred)
    - etag_key: optional hash/version key to avoid unnecessary payload writes
    - payload_mapper: optional function to reduce payload before storing
    Returns statistics and new watermark.
    """
    (lambda _m=query_meta(query_id): ensure_query(query_id, params={}) if (_m.get("params") is None) else None)()
    now = _now_iso()
    n_total = 0
    n_insert = 0
    n_update = 0
    max_time: Optional[str] = None
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> None:
                nonlocal n_total, n_insert, n_update, max_time
                for it in items:
                    n_total += 1
                    iid = str(it.get(id_key))
                    t = str(it.get(time_key) or "")
                    if not iid:
                        continue
                    if t:
                        if max_time is None or _iso_to_dt(t) > _iso_to_dt(max_time):
                            max_time = t
                    etag = str(it.get(etag_key)) if etag_key else None
                    payload = payload_mapper(it) if payload_mapper else it
                    pjson = json.dumps(payload, ensure_ascii=False)

                    # If etag provided, skip unnecessary writes when unchanged
                    if etag is not None:
                        cur = conn.execute(
                            "SELECT etag FROM items WHERE query_id=? AND item_id=?",
                            (query_id, iid),
                        )
                        row = cur.fetchone()
                        if row is not None and str(row[0] or "") == etag:
                            # Update time if newer even when payload unchanged
                            conn.execute(
                                "UPDATE items SET item_time=?, updated_at=? WHERE query_id=? AND item_id=?",
                                (t or None, now, query_id, iid),
                            )
                            continue

                    cur = conn.execute(
                        "SELECT 1 FROM items WHERE query_id=? AND item_id=?",
                        (query_id, iid),
                    )
                    if cur.fetchone() is None:
                        n_insert += 1
                        conn.execute(
                            """
                            INSERT INTO items(query_id, item_id, item_time, etag, payload, updated_at)
                            VALUES (?,?,?,?,?,?)
                            """,
                            (query_id, iid, t or None, etag, pjson, now),
                        )
                    else:
                        n_update += 1
                        conn.execute(
                            """
                            UPDATE items SET item_time=?, etag=?, payload=?, updated_at=?
                            WHERE query_id=? AND item_id=?
                            """,
                            (t or None, etag, pjson, now, query_id, iid),
                        )

                # Update query-level metadata
                if max_time is not None:
                    conn.execute(
                        "UPDATE queries SET last_item_time=?, last_fetch_at=?, updated_at=? WHERE id=?",
                        (max_time, now, now, query_id),
                    )
                else:
                    conn.execute(
                        "UPDATE queries SET last_fetch_at=?, updated_at=? WHERE id=?",
                        (now, now, query_id),
                    )
                conn.commit()

            _retry_on_locked(_write)
        finally:
            conn.close()
    return {
        "query_id": query_id,
        "total": n_total,
        "inserted": n_insert,
        "updated": n_update,
        "last_item_time": max_time or watermark(query_id),
    }


def list_items(
    query_id: str,
    *,
    since: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conn = _connect()
    try:
        if since is None:
            sql = "SELECT item_id, item_time, etag, payload, updated_at FROM items WHERE query_id=? ORDER BY item_time ASC"
            args: Tuple[Any, ...] = (query_id,)
        else:
            sql = "SELECT item_id, item_time, etag, payload, updated_at FROM items WHERE query_id=? AND (item_time >= ?) ORDER BY item_time ASC"
            args = (query_id, since)
        if limit is not None:
            sql += " LIMIT ?"
            args = (*args, int(limit))
        cur = conn.execute(sql, args)
        out: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            out.append(
                {
                    "item_id": r[0],
                    "item_time": r[1],
                    "etag": r[2],
                    "payload": json.loads(r[3] or "{}"),
                    "updated_at": r[4],
                }
            )
        return out
    finally:
        conn.close()


def reset_query(query_id: str) -> None:
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> None:
                conn.execute("DELETE FROM items WHERE query_id=?", (query_id,))
                conn.execute(
                    "UPDATE queries SET last_item_time=NULL, last_fetch_at=NULL, updated_at=? WHERE id=?",
                    (_now_iso(), query_id),
                )
                conn.commit()

            _retry_on_locked(_write)
        finally:
            conn.close()


def drop_query(query_id: str) -> None:
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> None:
                conn.execute("DELETE FROM items WHERE query_id=?", (query_id,))
                conn.execute("DELETE FROM queries WHERE id=?", (query_id,))
                conn.commit()

            _retry_on_locked(_write)
        finally:
            conn.close()


def vacuum() -> None:
    with _WRITE_LOCK:
        conn = _connect()
        try:
            def _write() -> None:
                conn.execute("VACUUM")
                conn.commit()

            _retry_on_locked(_write)
        finally:
            conn.close()