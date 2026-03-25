from __future__ import annotations

"""
Thin compatibility wrapper for legacy tests.

This module must not contain business logic. It exposes:
  - _tool_specs_full(strict=True|False): deterministic tool schema
  - run_agent_turn(session_id, message): delegates to orchestrator
"""

from typing import Any, Dict, List, Optional

from .orchestrator import handle_message


def _tool_specs_full(strict: bool = False) -> List[Dict[str, Any]]:
    def fn(name: str, args_schema: Dict[str, Any]) -> Dict[str, Any]:
        o = {"type": "function", "function": {"name": name, "parameters": args_schema}}
        if strict:
            o["function"]["strict"] = True
        return o

    def obj(props: Dict[str, Any], *, strict: bool = False) -> Dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False if strict else True,
            "properties": props,
            "required": list(props.keys()),
        }

    specs: List[Dict[str, Any]] = []
    specs.append(fn("chat", obj({"session_id": {"type": "string"}, "query": {"type": "string"}}, strict=strict)))
    specs.append(fn("get_session_context", obj({"session_id": {"type": "string"}}, strict=strict)))
    specs.append(
        fn(
            "ensure_recommendation",
            obj({
                "session_id": {"type": "string"},
                "topk": {"type": "integer", "minimum": 1, "maximum": 10},
                "refresh": {"type": "boolean"},
            }, strict=strict),
        )
    )
    specs.append(fn("resolve_reference", obj({"session_id": {"type": "string"}, "raw_reference": {"type": "string"}}, strict=strict)))
    specs.append(fn("explain_selection_set", obj({"session_id": {"type": "string"}}, strict=strict)))
    specs.append(fn("get_pick_detail", obj({"session_id": {"type": "string"}, "symbol": {"type": "string"}}, strict=strict)))
    return specs


def run_agent_turn(session_id: Optional[str], message: str) -> Dict[str, Any]:
    # Delegate to unified orchestrator to produce reply and right_panel
    return handle_message(session_id, message, None)

