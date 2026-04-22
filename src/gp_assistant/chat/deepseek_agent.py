from __future__ import annotations

from typing import Any, Dict, List

SYSTEM_PROMPT = "Use structured tool calls only."


def _tool_specs_full(strict: bool = True) -> List[Dict[str, Any]]:
    def _fn(name: str, properties: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": name,
                "strict": strict,
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                    "required": list(properties.keys()),
                },
            },
        }

    return [
        _fn("chat", {"message": {"type": "string"}}),
        _fn("ensure_recommendation", {"topk": {"type": "integer", "minimum": 1, "maximum": 20}, "refresh": {"type": "boolean"}}),
        _fn("get_pick_detail", {"symbol": {"type": "string"}}),
    ]
