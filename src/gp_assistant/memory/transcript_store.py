from __future__ import annotations

import json
from typing import List

from ..contracts.objects import TranscriptEvent
from ._sqlite import get_conn


def append_event(event: TranscriptEvent) -> None:
    with get_conn() as conn:
        conn.execute(
            'INSERT INTO transcript(session_id, seq, turn_id, role, content, created_at, meta_json) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (event.session_id, event.seq, event.turn_id, event.role, event.content, event.created_at, json.dumps(event.meta, ensure_ascii=False)),
        )


def next_seq(session_id: str) -> int:
    with get_conn() as conn:
        row = conn.execute('SELECT COALESCE(MAX(seq), 0) AS m FROM transcript WHERE session_id=?', (session_id,)).fetchone()
    return int(row['m']) + 1


def load_recent(session_id: str, limit: int = 12) -> List[TranscriptEvent]:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT seq, turn_id, session_id, role, content, created_at, meta_json FROM transcript WHERE session_id=? ORDER BY seq DESC LIMIT ?',
            (session_id, limit),
        ).fetchall()
    out = []
    for row in reversed(rows):
        out.append(TranscriptEvent(
            seq=int(row['seq']),
            turn_id=row['turn_id'],
            session_id=row['session_id'],
            role=row['role'],
            content=row['content'],
            created_at=row['created_at'],
            meta=json.loads(row['meta_json'] or '{}'),
        ))
    return out
