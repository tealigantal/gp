# 简介：多轮对话状态存储。使用 SQLite 持久化消息历史与最近一次推荐，
# 支持根据 session_id 复用上下文实现连续对话。
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.config import load_config
from ..core.paths import store_dir
from . import event_store


def _db_path() -> Path:
    p = store_dir() / "sessions" / "session.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_db_path()))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages(
            session_id TEXT,
            role TEXT,
            content TEXT,
            ts TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions(
            session_id TEXT PRIMARY KEY,
            created_at TEXT,
            last_recommend_json TEXT
        )
        """
    )
    conn.commit()
    return conn


def _now_iso() -> str:
    cfg = load_config()
    tz = timezone.utc
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(cfg.timezone)
    except Exception:
        pass
    return datetime.now(tz=tz).isoformat()


def ensure_session(session_id: Optional[str] = None) -> str:
    sid = session_id or datetime.utcnow().strftime("sess-%Y%m%d%H%M%S%f")
    conn = _connect()
    cur = conn.execute("SELECT session_id FROM sessions WHERE session_id=?", (sid,))
    if cur.fetchone() is None:
        conn.execute(
            "INSERT INTO sessions(session_id, created_at, last_recommend_json) VALUES (?,?,?)",
            (sid, _now_iso(), None),
        )
        conn.commit()
    conn.close()
    # Also ensure conversation and participant in event store
    try:
        event_store.ensure_conversation(sid, title=sid, conv_type="chat")
        event_store.ensure_participant(sid)
    except Exception:
        # do not fail chat if event store init has an issue
        pass
    return sid


def append_message(session_id: str, role: str, content: str) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO messages(session_id, role, content, ts) VALUES (?,?,?,?)",
        (session_id, role, content, _now_iso()),
    )
    conn.commit()
    conn.close()
    # Mirror into Event Log (best-effort)
    try:
        author_id = role or "user"
        event_store.append_text_message(session_id, author_id=author_id, content=content)
    except Exception:
        # keep silent to avoid breaking legacy path
        pass


def load_history(session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    conn = _connect()
    cur = conn.execute(
        "SELECT role, content, ts FROM messages WHERE session_id=? ORDER BY ts ASC LIMIT ?",
        (session_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "ts": r[2]} for r in rows]


def save_last_recommend(session_id: str, obj: Dict[str, Any]) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE sessions SET last_recommend_json=? WHERE session_id=?",
        (json.dumps(obj, ensure_ascii=False), session_id),
    )
    conn.commit()
    conn.close()


def load_last_recommend(session_id: str) -> Optional[Dict[str, Any]]:
    conn = _connect()
    cur = conn.execute("SELECT last_recommend_json FROM sessions WHERE session_id=?", (session_id,))
    row = cur.fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None
