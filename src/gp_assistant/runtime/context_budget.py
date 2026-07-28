from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..core.errors import LLMPayloadBudgetExceeded
from ..core.logging import logger


ROUTING_PAYLOAD_LIMIT_BYTES = 600_000
LLM_HARD_CAP_BYTES = 2_300_000

_REF_KEYS = {
    "run_id",
    "artifact_id",
    "book_version",
    "decision_context_snapshot_id",
    "symbol",
    "rank",
}


def encode_json_bytes(value: Any) -> bytes:
    """Serialize exactly as the LLM transport sends the payload."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def serialized_size_bytes(value: Any) -> int:
    return len(encode_json_bytes(value))


def _append_block(rows: List[Dict[str, Any]], name: str, value: Any, *, compressed: bool) -> None:
    rows.append(
        {
            "name": name,
            "bytes": serialized_size_bytes(value),
            "compressed": bool(compressed),
        }
    )


def _decoded_content(value: Any) -> Any:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _payload_blocks(value: Any, *, compressed: bool) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(value, Mapping):
        _append_block(rows, "payload", value, compressed=compressed)
        return rows

    for key, item in value.items():
        if key != "messages":
            _append_block(rows, str(key), item, compressed=compressed)
            continue

        _append_block(rows, "messages", item, compressed=compressed)
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes, bytearray)):
            continue
        for index, message in enumerate(item):
            if not isinstance(message, Mapping):
                continue
            role = str(message.get("role") or "unknown")
            content = message.get("content")
            _append_block(rows, f"messages[{index}].{role}.content", content, compressed=compressed)
            decoded = _decoded_content(content)
            if not isinstance(decoded, Mapping):
                continue
            for root_key in ("context", "tool_evidence_context", "judgment_result", "recent_dialogue"):
                root_value = decoded.get(root_key)
                if root_value is None:
                    continue
                _append_block(
                    rows,
                    f"messages[{index}].{role}.{root_key}",
                    root_value,
                    compressed=compressed,
                )
                if isinstance(root_value, Mapping):
                    for child_key, child_value in root_value.items():
                        _append_block(
                            rows,
                            f"messages[{index}].{role}.{root_key}.{child_key}",
                            child_value,
                            compressed=compressed,
                        )
    return rows


def _safe_ref_rows(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, Mapping):
        row = {key: value.get(key) for key in _REF_KEYS if value.get(key) is not None}
        if row and ("symbol" in row or "run_id" in row or "artifact_id" in row):
            yield row
        for child in value.values():
            yield from _safe_ref_rows(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _safe_ref_rows(child)
    elif isinstance(value, str):
        decoded = _decoded_content(value)
        if decoded is not None:
            yield from _safe_ref_rows(decoded)


def _context_refs(value: Any, *, limit: int = 50) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in _safe_ref_rows(value):
        key = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        refs.append(row)
        if len(refs) >= limit:
            break
    return refs


def context_size_report(
    value: Any,
    *,
    stage: str,
    limit_bytes: int,
    compressed: bool = False,
    compression_steps: Iterable[str] | None = None,
) -> Dict[str, Any]:
    """Return size-only diagnostics; never copy prompt or evidence content."""

    total_bytes = serialized_size_bytes(value)
    return {
        "stage": str(stage),
        "total_bytes": total_bytes,
        "limit_bytes": int(limit_bytes),
        "hard_cap_bytes": LLM_HARD_CAP_BYTES,
        "within_limit": total_bytes <= int(limit_bytes),
        "compressed": bool(compressed),
        "compression_steps": [str(item) for item in (compression_steps or [])],
        "blocks": _payload_blocks(value, compressed=compressed),
        "context_refs": _context_refs(value),
    }


def encode_llm_payload(
    payload: Dict[str, Any],
    *,
    stage: str,
    limit_bytes: int | None = None,
    compressed: bool = False,
    compression_steps: Iterable[str] | None = None,
) -> tuple[bytes, Dict[str, Any]]:
    effective_limit = min(int(limit_bytes or LLM_HARD_CAP_BYTES), LLM_HARD_CAP_BYTES)
    data = encode_json_bytes(payload)
    report = context_size_report(
        payload,
        stage=stage,
        limit_bytes=effective_limit,
        compressed=compressed,
        compression_steps=compression_steps,
    )
    log_payload = {
        "stage": report["stage"],
        "total_bytes": report["total_bytes"],
        "limit_bytes": report["limit_bytes"],
        "hard_cap_bytes": report["hard_cap_bytes"],
        "within_limit": report["within_limit"],
        "compressed": report["compressed"],
        "blocks": report["blocks"],
        "context_ref_count": len(report["context_refs"]),
    }
    if len(data) > effective_limit:
        logger.warning("[llm-budget] rejected %s", json.dumps(log_payload, ensure_ascii=False, separators=(",", ":")))
        raise LLMPayloadBudgetExceeded(
            stage=stage,
            actual_bytes=len(data),
            limit_bytes=effective_limit,
            budget_report=report,
        )
    logger.info("[llm-budget] accepted %s", json.dumps(log_payload, ensure_ascii=False, separators=(",", ":")))
    return data, report
