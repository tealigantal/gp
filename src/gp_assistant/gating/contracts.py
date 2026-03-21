from __future__ import annotations

from typing import Any, Dict, List


DECISION_ALLOW = "allow"
DECISION_DEGRADED = "degraded"
DECISION_BLOCKED = "blocked"


def make_gating_decision(level: str = "item") -> Dict[str, Any]:
    return {
        "decision": DECISION_ALLOW,
        "level": level,  # 'item' | 'run'
        "reasons": [],
        "triggered_rules": [],
        "warnings": [],
        "inputs_snapshot": {},
        "fallback_used": False,
    }


def attach_item_gating(item: Dict[str, Any], decision: Dict[str, Any]) -> None:
    item["gating_decision"] = decision


def attach_run_gating(artifact: Dict[str, Any], decision: Dict[str, Any]) -> None:
    artifact["run_gating"] = decision

