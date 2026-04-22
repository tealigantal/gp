from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ..contracts.objects import TranscriptEvent
from ..memory.session_store import default_session, load_session, save_session
from ..memory.transcript_store import append_event, next_seq
from ..runtime.utils import now_iso
from ..core.paths import store_dir


def _legacy_root() -> Path:
    p = store_dir() / "chat_compat"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _extra_path(session_id: str) -> Path:
    return _legacy_root() / f"{session_id}.json"


def _load_extra(session_id: str) -> Dict[str, Any]:
    p = _extra_path(session_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_extra(session_id: str, data: Dict[str, Any]) -> None:
    _extra_path(session_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_session(session_id: str | None) -> str:
    sid = session_id or "default"
    session = load_session(sid)
    if session.session_id != sid:
        session = default_session(sid)
    save_session(session)
    return sid


def get_state(session_id: str) -> Dict[str, Any]:
    session = load_session(session_id)
    data = session.model_dump()
    data.update(_load_extra(session_id))
    return data


def update_state(session_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    session = load_session(session_id)
    extra = _load_extra(session_id)
    for key, value in (updates or {}).items():
        if hasattr(session, key):
            setattr(session, key, value)
        else:
            extra[key] = value
    save_session(session)
    _save_extra(session_id, extra)
    return get_state(session_id)


def append_message(session_id: str, role: str, content: str) -> None:
    sid = ensure_session(session_id)
    seq = next_seq(sid)
    event = TranscriptEvent(
        seq=seq,
        turn_id=f"compat-{seq}",
        session_id=sid,
        role=role,
        content=content,
        created_at=now_iso(),
        meta={},
    )
    append_event(event)
