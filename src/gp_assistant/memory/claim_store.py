from __future__ import annotations

import json
from typing import List

from ..contracts.objects import Claim
from ._sqlite import get_conn


def save_claims(claims: List[Claim]) -> None:
    if not claims:
        return
    with get_conn() as conn:
        for claim in claims:
            conn.execute(
                'INSERT OR REPLACE INTO claims(claim_id, session_id, subject_type, subject_id, predicate, value_json, evidence_refs_json, turn_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (
                    claim.claim_id,
                    claim.session_id,
                    claim.subject_type,
                    claim.subject_id,
                    claim.predicate,
                    json.dumps(claim.value, ensure_ascii=False),
                    json.dumps(claim.evidence_refs, ensure_ascii=False),
                    claim.turn_id,
                    claim.created_at,
                ),
            )


def load_recent_claims(session_id: str, limit: int = 20) -> List[Claim]:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT * FROM claims WHERE session_id=? ORDER BY created_at DESC LIMIT ?',
            (session_id, limit),
        ).fetchall()
    out = []
    for row in rows:
        out.append(Claim(
            claim_id=row['claim_id'],
            session_id=row['session_id'],
            subject_type=row['subject_type'],
            subject_id=row['subject_id'],
            predicate=row['predicate'],
            value=json.loads(row['value_json'] or '{}'),
            evidence_refs=json.loads(row['evidence_refs_json'] or '[]'),
            turn_id=row['turn_id'],
            created_at=row['created_at'],
        ))
    return out
