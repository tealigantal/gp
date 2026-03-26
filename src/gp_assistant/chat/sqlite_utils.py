from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
import sqlite3
import time

from ..core.config import load_config
from ..core.paths import store_dir


def db_path() -> Path:
    p = store_dir() / "sessions" / "session.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def apply_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")
    except Exception:
        pass


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=15.0)
    apply_sqlite_pragmas(conn)
    return conn


def retry_on_locked(fn: Callable[[], Any], *, retries: int = 8, base_delay: float = 0.08):
    for i in range(max(1, retries)):
        try:
            return fn()
        except sqlite3.OperationalError as e:  # noqa: BLE001
            msg = str(e).lower()
            if "database is locked" in msg or "database is busy" in msg:
                time.sleep(base_delay * (2 ** i))
                continue
            raise
    return fn()


def now_iso() -> str:
    cfg = load_config()
    tz = timezone.utc
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(getattr(cfg, "timezone", "Asia/Shanghai"))
    except Exception:
        pass
    return datetime.now(tz=tz).isoformat()

