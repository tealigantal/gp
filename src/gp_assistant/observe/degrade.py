from __future__ import annotations

from typing import Dict, Any, List

from ..core.logging import logger


_warned: set[str] = set()


def warn_once(reason_code: str, line: str) -> None:
    key = f"{reason_code}:{line}"
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(f"[DEGRADED] {line}")


def record(debug: Dict[str, Any], reason_code: str, detail: Dict[str, Any] | None = None) -> None:
    if detail is None:
        detail = {}
    debug.setdefault("degraded", True)
    reasons: List[Dict[str, Any]] = debug.setdefault("degrade_reasons", [])  # type: ignore[assignment]
    reasons.append({"reason_code": reason_code, "detail": detail})


def apply_tradeable_flag(tool_result: Any) -> Any:
    """If debug shows degradation, mark tradeable=false and prefix message.

    Expects tool_result to have attributes: data (dict), message (str), tradeable (optional).
    """
    try:
        data = tool_result.data or {}
        debug = data.get("debug") or {}
        degraded = bool(debug.get("degraded"))
        if degraded:
            # Collect concise reason codes (up to 2 in prefix)
            rs = [str(x.get("reason_code")) for x in debug.get("degrade_reasons", [])]
            prefix = "NOT_TRADEABLE: " + (", ".join(rs[:2]) if rs else "UNKNOWN")
            # Mark tradeable false at top-level and inside data for consumers
            tool_result.tradeable = False
            data["tradeable"] = False
            # Apply prefix once
            base_msg = str(getattr(tool_result, "message", "")).strip()
            if not base_msg.startswith("NOT_TRADEABLE:"):
                tool_result.message = f"{prefix} | {base_msg}" if base_msg else prefix
            tool_result.data = data
        else:
            tool_result.tradeable = True
            data["tradeable"] = True
            tool_result.data = data
    except Exception:
        # Do not break runs if flagging fails
        pass
    return tool_result
