from __future__ import annotations

"""
Session state store: persists chat messages and structured session state in SQLite.

This module now uses shared sqlite_utils for DB connection and time helpers to
avoid duplicating pragmas and retry loops.
"""

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import event_store
from .sqlite_utils import connect_db as _db_connect, now_iso as _now_iso


def _connect() -> sqlite3.Connection:
    conn = _db_connect()
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
                    import time as _t
                    _t.sleep(0.05 * (2 ** i))
                    continue
                raise
    finally:
        conn.close()
    # Also ensure conversation and participant in event store
    try:
        event_store.ensure_conversation(sid, title=sid, conv_type="chat")
        event_store.ensure_participant(sid)
    except Exception:
        pass
    return sid


def append_message(
    session_id: str,
    role: str,
    content: str,
    message_id: Optional[str] = None,
    *,
    require_event: bool = False,
) -> Optional[str]:
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
    except Exception:
        if require_event:
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
    # Legacy fields (kept for backward compatibility)
    "current_focus_symbol": None,
    "current_focus_name": None,
    "last_recommend_symbols": [],
    "last_analyze_symbol": None,
    "last_tool_trace": None,
    "last_agent_trace": None,
    "last_as_of": None,
    "pending_ambiguity": None,
    "last_followup_type": None,
    # Phase 1: run-aware, multi-symbol aware session fields
    "active_run_id": None,
    "active_symbols": [],
    "focused_symbol": None,
    "compare_symbols": [],
    "last_intent": None,
    "last_message_type": None,
    "last_refresh_at": None,
    # Phase 2: run reuse + planner trace
    "previous_run_id": None,
    "previous_active_symbols": [],
    "last_planner_output": None,
    # Layered turn/memory fields (phase 3)
    "last_right_panel": {},
    "pending_action": None,
    "pending_symbols": [],
    "pending_cursor": None,
    "last_reference_resolution": None,
    "last_surface_kind": None,
    "last_tool_results_summary": {},
    "last_visible_assistant_summary": {},
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
        for k in _STATE_DEFAULTS.keys():
            v = raw.get(k, None)
            if v is not None:
                st[k] = v
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
    # Accept only known keys; keep lists as lists
    sanitized: Dict[str, Any] = {}
    for k, v in updates.items():
        if k not in _STATE_DEFAULTS:
            continue
        if isinstance(_STATE_DEFAULTS[k], list):
            try:
                vv = list(v) if v is not None else []
            except Exception:
                vv = []
            sanitized[k] = vv
        else:
            sanitized[k] = v
    # Mirror focused_symbol to legacy field for backward compatibility
    if "focused_symbol" in sanitized and sanitized.get("focused_symbol") is not None:
        sanitized.setdefault("current_focus_symbol", sanitized.get("focused_symbol"))
    cur.update(sanitized)
    _save_state_raw(session_id, cur)
    return cur


def set_focus(session_id: str, symbol: Optional[str], reason: Optional[str] = None, name: Optional[str] = None) -> Dict[str, Any]:
    st = update_state(
        session_id,
        {
            "current_focus_symbol": symbol,
            "focused_symbol": symbol,
            "current_focus_name": name,
            "last_analyze_symbol": symbol,
        },
    )
    # Internal-only event: do NOT materialize into user-visible message stream
    try:
        if symbol:
            event_store.append_event(
                session_id,
                event_id=f"focus-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}",
                type="internal.focus_changed",
                data={
                    "symbol": symbol,
                    "name": name,
                    "reason": reason,
                },
                actor_id="assistant",
            )
    except Exception:
        pass
    return st


def get_focus(session_id: str) -> Optional[str]:
    st = get_state(session_id)
    s = st.get("focused_symbol") or st.get("current_focus_symbol")
    return str(s) if s else None


def set_last_recommend_and_symbols(session_id: str, obj: Dict[str, Any]) -> None:
    save_last_recommend(session_id, obj)
    syms: List[str] = []
    try:
        picks = (obj or {}).get("picks") or []
        if isinstance(picks, list):
            for p in picks:
                s = str((p or {}).get("symbol") or "").strip()
                if s:
                    syms.append(s)
    except Exception:
        pass
    # Migrate previous context then set active
    st0 = get_state(session_id)
    prev_run = st0.get("active_run_id")
    prev_syms = st0.get("active_symbols") or []
    update_state(session_id, {"previous_run_id": prev_run, "previous_active_symbols": list(prev_syms or [])})
    update_state(
        session_id,
        {
            "last_recommend_symbols": syms,
            "active_symbols": syms,
            "last_as_of": (obj or {}).get("as_of"),
            # Fix: prefer run_id first, fallback to as_of
            "active_run_id": (obj or {}).get("run_id") or (obj or {}).get("as_of"),
        },
    )


def get_last_symbols(session_id: str) -> List[str]:
    st = get_state(session_id)
    syms = st.get("last_recommend_symbols") or []
    return list(syms) if isinstance(syms, list) else []


# Phase 1 helpers (minimal API)


def set_active_run(session_id: str, run_id: Optional[str], symbols: Optional[List[str]] = None) -> Dict[str, Any]:
    return update_state(
        session_id,
        {
            "active_run_id": run_id,
            "active_symbols": list(symbols or []),
        },
    )


def set_compare_symbols(session_id: str, symbols: List[str]) -> Dict[str, Any]:
    return update_state(session_id, {"compare_symbols": list(symbols or [])})


def set_last_intent(session_id: str, name: Optional[str], message_type: Optional[str] = None) -> Dict[str, Any]:
    return update_state(session_id, {"last_intent": name, "last_message_type": message_type})


def set_last_refresh(session_id: str) -> Dict[str, Any]:
    return update_state(session_id, {"last_refresh_at": datetime.now(timezone.utc).isoformat()})

