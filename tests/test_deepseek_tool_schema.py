from __future__ import annotations

from typing import Any, Dict, List


def _get_specs() -> List[Dict[str, Any]]:
    from gp_assistant.chat.deepseek_agent import _tool_specs_full

    return _tool_specs_full(strict=True)


def test_strict_flag_and_object_shape():
    specs = _get_specs()
    assert isinstance(specs, list) and specs
    for s in specs:
        assert s.get("type") == "function"
        fn = s.get("function") or {}
        assert fn.get("strict") is True
        params = fn.get("parameters") or {}
        # all object schemas should be strict-safe
        assert params.get("type") == "object"
        assert params.get("additionalProperties") is False
        props = params.get("properties") or {}
        req = set(params.get("required") or [])
        # required should at least cover all properties keys
        assert set(props.keys()).issubset(req)

    # ensure chat tool exists and is strict-safe
    names = [((s.get("function") or {}).get("name")) for s in specs]
    assert "chat" in names


def test_ensure_recommendation_schema_strict():
    specs = _get_specs()
    target = None
    for s in specs:
        if (s.get("function") or {}).get("name") == "ensure_recommendation":
            target = (s.get("function") or {}).get("parameters")
            break
    assert isinstance(target, dict)
    props = target.get("properties") or {}
    assert set(target.get("required") or []) == set(props.keys())
    # No nullable union types; explicit types only
    assert isinstance(props.get("topk"), dict) and props["topk"].get("type") == "integer"
    assert isinstance(props.get("refresh"), dict) and props["refresh"].get("type") == "boolean"
    # Reasonable constraints present
    assert props["topk"].get("minimum", 0) >= 1
    assert props["topk"].get("maximum", 0) >= props["topk"].get("minimum", 1)
