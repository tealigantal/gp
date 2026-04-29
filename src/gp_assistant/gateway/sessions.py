from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from ..memory.service import get_session_overview

_TURN_META_BLOCKLIST = {"tool_trace"}


def _sanitize_turn(turn: Dict[str, Any]) -> Dict[str, Any]:
    clean = deepcopy(turn)
    meta = clean.get("meta")
    if isinstance(meta, dict):
        for key in _TURN_META_BLOCKLIST:
            meta.pop(key, None)
    return clean


def sanitize_chat_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    clean = deepcopy(payload)
    clean.pop("tool_trace", None)
    return clean


def get_session_payload(session_id: str) -> Dict[str, Any]:
    payload = get_session_overview(session_id)
    payload["recent_turns"] = [_sanitize_turn(turn) for turn in payload.get("recent_turns", [])]
    payload["recent_claims"] = []
    return payload


def get_session_diagnostics(session_id: str) -> Dict[str, Any]:
    payload = get_session_payload(session_id)
    session = dict(payload.get("session") or {})
    turns = list(payload.get("recent_turns") or [])
    assistant_messages = []
    latest_assistant = None
    for turn in reversed(turns):
        if turn.get("role") != "assistant":
            continue
        meta = dict(turn.get("meta") or {})
        message = meta.get("message")
        if not isinstance(message, dict):
            continue
        item = {
            "turn_id": turn.get("turn_id"),
            "seq": turn.get("seq"),
            "created_at": turn.get("created_at"),
            "message_kind": message.get("message_kind"),
            "narrative_text": message.get("narrative_text"),
            "symbol": message.get("symbol") or (message.get("pick") or {}).get("symbol") or (message.get("live_check") or {}).get("symbol"),
            "run_action": (message.get("run") or {}).get("run_action") if isinstance(message.get("run"), dict) else None,
            "followup_suggestions": list(message.get("followup_suggestions") or []),
        }
        assistant_messages.append(item)
        if latest_assistant is None:
            latest_assistant = item
        if len(assistant_messages) >= 6:
            break
    return {
        "session_id": session_id,
        "focus": {
            "active_run_id": session.get("active_run_id"),
            "previous_run_id": session.get("previous_run_id"),
            "last_focus_symbol": session.get("last_focus_symbol"),
            "last_focus_rank": session.get("last_focus_rank"),
            "compare_set": list(session.get("compare_set") or []),
        },
        "latest_assistant": latest_assistant,
        "assistant_messages": assistant_messages,
    }
