from __future__ import annotations

from typing import Any, Dict, List


def empty_workbench_snapshot() -> Dict[str, Any]:
    return {
        "as_of": None,
        "recommend": {},
        "validation_summary": {"parts": {}},
        "portfolio": {"positions": [], "pending_intents": [], "recent_events": []},
        "intents_preview": [],
        "execution_events": [],
        "live_shadow_summary": {"available": False, "dates": []},
        "warnings": [],
        "source_status": {},
    }

