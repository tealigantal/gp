from __future__ import annotations

from typing import Any, Dict

from jsonschema import validate


SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["date", "tier", "market_env", "main_themes", "candidate_pool_summary", "top10", "champion", "action_list", "disclaimer"],
    "properties": {
        "date": {"type": "string"},
        "tier": {"type": "string", "enum": ["low", "mid", "high"]},
        "market_env": {"type": "string", "enum": ["A", "B", "C", "D"]},
        "main_themes": {"type": "array", "items": {"type": "string"}},
        "candidate_pool_summary": {"type": "object"},
        "top10": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "indicators", "q_level", "chip_band", "announcements", "actions", "risk"],
                "properties": {
                    "code": {"type": "string"},
                    "indicators": {"type": "object"},
                    "q_level": {"type": "integer", "minimum": 0, "maximum": 3},
                    "chip_band": {"type": "object"},
                    "announcements": {"type": "object"},
                    "actions": {"type": "object"},
                    "risk": {"type": "object"},
                },
            },
        },
        "champion": {"type": "object"},
        "action_list": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "disclaimer": {"type": "string"},
    },
}


def validate_report(obj: Dict[str, Any]) -> None:
    validate(instance=obj, schema=SCHEMA)

