from __future__ import annotations

from ..contracts.objects import SessionState
from ._sqlite import get_conn
from ..runtime.utils import now_iso


def default_session(session_id: str) -> SessionState:
    ts = now_iso()
    return SessionState(session_id=session_id, created_at=ts, updated_at=ts)


def load_session(session_id: str) -> SessionState:
    with get_conn() as conn:
        row = conn.execute('SELECT data_json FROM sessions WHERE session_id=?', (session_id,)).fetchone()
    if not row:
        return default_session(session_id)
    return SessionState.model_validate_json(row['data_json'])


def save_session(session: SessionState) -> None:
    session.updated_at = now_iso()
    with get_conn() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO sessions(session_id, data_json, updated_at) VALUES (?, ?, ?)',
            (session.session_id, session.model_dump_json(), session.updated_at),
        )


def list_sessions(limit: int = 50) -> list[SessionState]:
    with get_conn() as conn:
        rows = conn.execute('SELECT data_json FROM sessions ORDER BY updated_at DESC LIMIT ?', (limit,)).fetchall()
    return [SessionState.model_validate_json(r['data_json']) for r in rows]
