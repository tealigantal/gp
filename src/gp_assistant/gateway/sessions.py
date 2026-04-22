from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from ..memory.service import get_session_overview

_TURN_META_BLOCKLIST = {"planner_trace", "evidence_refs"}


def _sanitize_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    clean = deepcopy(turn)
    meta = clean.get("meta")
    if isinstance(meta, dict):
        for key in _TURN_META_BLOCKLIST:
            meta.pop(key, None)
    return clean


def sanitize_chat_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    clean = deepcopy(payload)
    clean["planner_trace"] = {}
    clean["evidence_refs"] = []
    return clean


def get_session_payload(session_id: str) -> Dict[str, Any]:
    payload = get_session_overview(session_id)
    payload["recent_turns"] = [_sanitize_turn(turn) for turn in payload.get("recent_turns", [])]
    payload["recent_claims"] = []
    return payload
