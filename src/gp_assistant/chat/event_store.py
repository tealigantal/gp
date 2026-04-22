from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from ..core.paths import store_dir
from ..runtime.utils import now_iso


def _root() -> Path:
    p = store_dir() / "chat_events"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(conversation_id: str) -> Path:
    return _root() / f"{conversation_id}.jsonl"


def ensure_conversation(conversation_id: str, title: str | None = None, conv_type: str | None = None) -> Dict[str, Any]:
    _path(conversation_id).touch(exist_ok=True)
    return {"id": conversation_id, "title": title or conversation_id, "type": conv_type or "chat"}


def ensure_participant(conversation_id: str, actor_id: str = "assistant") -> Dict[str, Any]:
    ensure_conversation(conversation_id)
    return {"conversation_id": conversation_id, "actor_id": actor_id}


def append_event(conversation_id: str, *, event_id: str, type: str, data: Dict[str, Any], actor_id: str | None = None) -> Dict[str, Any]:
    payload = {
        "id": event_id,
        "type": type,
        "actor_id": actor_id or "assistant",
        "created_at": now_iso(),
        "data": data or {},
    }
    with _path(conversation_id).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def list_events_after(conversation_id: str, after_seq: int, limit: int = 200) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    p = _path(conversation_id)
    if not p.exists():
        return out
    for idx, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if idx <= after_seq or not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        obj.setdefault("seq", idx)
        out.append(obj)
    return out[:limit]


def list_conversations() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in sorted(_root().glob("*.jsonl"), key=lambda x: x.stat().st_mtime):
        out.append({"id": p.stem, "updated_at": p.stat().st_mtime})
    return out
