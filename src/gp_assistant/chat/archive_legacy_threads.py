from __future__ import annotations

import json
from typing import Any, Dict, List

from ..core.paths import store_dir
from . import event_store


def archive_legacy_items() -> Dict[str, Any]:
    """Scan conv_messages for non-assistant_bundle assistant items and archive them.

    Does not delete; UI will hide them by read-model rules. This creates a
    simple JSON snapshot for inspection under store/assistant_legacy_archive/.
    """
    base = store_dir() / "assistant_legacy_archive"
    base.mkdir(parents=True, exist_ok=True)
    conversations = event_store.list_conversations()
    archived = 0
    files: List[str] = []
    for c in conversations:
        cid = c.get("id")
        if not cid:
            continue
        data = event_store.export_conversation(cid)
        # Filter legacy assistant items
        events = data.get("events") or []
        legacy = []
        for ev in events:
            if ev.get("type") == "message.created":
                d = ev.get("data") or {}
                k = d.get("kind")
                if k and k != "assistant_bundle" and ev.get("actor_id") == "assistant":
                    legacy.append(ev)
        if legacy:
            path = base / f"{cid}.json"
            path.write_text(json.dumps({"conversation_id": cid, "legacy_events": legacy}, ensure_ascii=False, indent=2), encoding="utf-8")
            files.append(str(path))
            archived += len(legacy)
    return {"ok": True, "archived_events": archived, "files": files}


if __name__ == "__main__":
    r = archive_legacy_items()
    print(json.dumps(r, ensure_ascii=False, indent=2))

