from __future__ import annotations

import json
from typing import Any, Dict

from ._sqlite import get_conn
from ..runtime.utils import now_iso


def load_preferences(session_id: str) -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute('SELECT data_json FROM preferences WHERE session_id=?', (session_id,)).fetchone()
    return json.loads(row['data_json']) if row else {}


def save_preferences(session_id: str, prefs: Dict[str, Any]) -> None:
    with get_conn() as conn:
        conn.execute(
            'INSERT OR REPLACE INTO preferences(session_id, data_json, updated_at) VALUES (?, ?, ?)',
            (session_id, json.dumps(prefs, ensure_ascii=False), now_iso()),
        )
