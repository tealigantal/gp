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
import time


def _db_path() -> Path:
    p = store_dir() / "sessions" / "session.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _connect() -> sqlite3.Connection:
    # Align SQLite pragmas with event_store to mitigate 'database is locked'
    conn = sqlite3.connect(str(_db_path()), timeout=15.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=10000")  # 10s
    except Exception:
        pass
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
            last_recommend_json TEXT,
            state_json TEXT
        )
        """
    )
    # Best-effort migration: add state_json when missing
    try:
        cur = conn.execute("PRAGMA table_info(sessions)")
        cols = {str(r[1]) for r in cur.fetchall()}
        if "state_json" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN state_json TEXT")
            conn.commit()
    except Exception:
        pass
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
    try:
        # Retry small loop for locked
        for i in range(6):
            try:
                cur = conn.execute("SELECT session_id FROM sessions WHERE session_id=?", (sid,))
                if cur.fetchone() is None:
                    conn.execute(
                        "INSERT INTO sessions(session_id, created_at, last_recommend_json, state_json) VALUES (?,?,?,?)",
                        (sid, _now_iso(), None, None),
                    )
                    conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    time.sleep(0.05 * (2 ** i))
                    continue
                raise
    finally:
        conn.close()
    # Also ensure conversation and participant in event store
    try:
        event_store.ensure_conversation(sid, title=sid, conv_type="chat")
        event_store.ensure_participant(sid)
    except Exception:
        # do not fail chat if event store init has an issue
        pass
    return sid


def append_message(session_id: str, role: str, content: str, message_id: Optional[str] = None, *, require_event: bool = False) -> Optional[str]:
    conn = _connect()
    try:
        for i in range(6):
            try:
                conn.execute(
                    "INSERT INTO messages(session_id, role, content, ts) VALUES (?,?,?,?)",
                    (session_id, role, content, _now_iso()),
                )
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    import time as _t
                    _t.sleep(0.05 * (2 ** i))
                    continue
                raise
    finally:
        conn.close()
    # Mirror into Event Log (best-effort); return the event id if available
    try:
        author_id = role or "user"
        _, ev = event_store.append_text_message(session_id, author_id=author_id, content=content, message_id=message_id)
        return str(ev.get("id"))
    except Exception as e:  # noqa: BLE001
        if require_event:
            # Fail fast to keep backend as single source of truth
            raise
        return message_id


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
    try:
        for i in range(6):
            try:
                conn.execute(
                    "UPDATE sessions SET last_recommend_json=? WHERE session_id=?",
                    (json.dumps(obj, ensure_ascii=False), session_id),
                )
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    import time as _t
                    _t.sleep(0.05 * (2 ** i))
                    continue
                raise
    finally:
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


# ---------------- Structured session state ----------------

_STATE_DEFAULTS = {
    "current_focus_symbol": None,
    "current_focus_name": None,
    "last_recommend_symbols": [],
    "last_analyze_symbol": None,
    "last_tool_trace": None,
    "last_as_of": None,
    "pending_ambiguity": None,
    "last_followup_type": None,
}


def _load_state_raw(session_id: str) -> Dict[str, Any]:
    conn = _connect()
    try:
        cur = conn.execute("SELECT state_json FROM sessions WHERE session_id=?", (session_id,))
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    try:
        return json.loads(row[0] or "{}") if row[0] else {}
    except Exception:
        return {}


def _save_state_raw(session_id: str, state: Dict[str, Any]) -> None:
    conn = _connect()
    try:
        for i in range(6):
            try:
                conn.execute(
                    "UPDATE sessions SET state_json=? WHERE session_id=?",
                    (json.dumps(state, ensure_ascii=False), session_id),
                )
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    import time as _t
                    _t.sleep(0.05 * (2 ** i))
                    continue
                raise
    finally:
        conn.close()


def get_state(session_id: str) -> Dict[str, Any]:
    st = dict(_STATE_DEFAULTS)
    raw = _load_state_raw(session_id)
    if isinstance(raw, dict):
        st.update({k: raw.get(k) for k in _STATE_DEFAULTS.keys()})
    # derive last_recommend_symbols from last_recommend if missing
    if not st.get("last_recommend_symbols"):
        try:
            last = load_last_recommend(session_id)
            picks = (last or {}).get("picks") or []
            if isinstance(picks, list):
                syms = []
                for p in picks:
                    try:
                        s = str((p or {}).get("symbol") or "").strip()
                        if s:
                            syms.append(s)
                    except Exception:
                        continue
                st["last_recommend_symbols"] = syms
        except Exception:
            pass
    return st


def update_state(session_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    cur = get_state(session_id)
    cur.update({k: v for k, v in updates.items() if k in _STATE_DEFAULTS})
    _save_state_raw(session_id, cur)
    return cur


def set_focus(session_id: str, symbol: Optional[str], reason: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    st = update_state(session_id, {
        "current_focus_symbol": symbol,
        "current_focus_name": name,
        "last_analyze_symbol": symbol,
    })
    try:
        # log a small event message for focus change (best-effort)
        if symbol:
            event_store.append_event(
                session_id,
                event_id=f"focus-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
                type="message.created",
                data={
                    "kind": "note",
                    "message_id": f"focus-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
                    "content": f"[focus] {symbol} {('('+reason+')') if reason else ''}",
                },
                actor_id="assistant",
            )
    except Exception:
        pass
    return st


def get_focus(session_id: str) -> Optional[str]:
    st = get_state(session_id)
    s = st.get("current_focus_symbol")
    return str(s) if s else None


def set_last_recommend_and_symbols(session_id: str, obj: Dict[str, Any]) -> None:
    save_last_recommend(session_id, obj)
    syms: list[str] = []
    try:
        picks = (obj or {}).get("picks") or []
        if isinstance(picks, list):
            for p in picks:
                s = str((p or {}).get("symbol") or "").strip()
                if s:
                    syms.append(s)
    except Exception:
        pass
    update_state(session_id, {"last_recommend_symbols": syms, "last_as_of": (obj or {}).get("as_of")})


def get_last_symbols(session_id: str) -> list[str]:
    st = get_state(session_id)
    syms = st.get("last_recommend_symbols") or []
    return list(syms) if isinstance(syms, list) else []
