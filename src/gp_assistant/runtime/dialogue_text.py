from __future__ import annotations

from typing import Any, Iterable, List, Optional


def intraday_runtime_enabled() -> bool:
    return False


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _looks_like_internal_marker(text: str) -> bool:
    lowered = text.lower()
    if lowered.startswith("generated ") and " picks" in lowered:
        return True
    if lowered == "intraday_runtime_disabled":
        return False
    if "=" in text and not _has_cjk(text):
        return True
    if "_" in text and lowered == text and not _has_cjk(text):
        return True
    return False


def clean_user_reason(value: Any) -> Optional[str]:
    text = _as_text(value)
    if not text:
        return None
    if text.lower() == "intraday_runtime_disabled":
        return "当前只使用日线计划模块。"
    if _looks_like_internal_marker(text):
        return None
    return text


def clean_user_reasons(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    for value in values:
        cleaned = clean_user_reason(value)
        if cleaned:
            out.append(cleaned)
    return list(dict.fromkeys(out))


def explain_observation_reasons(values: Iterable[Any]) -> str:
    cleaned = clean_user_reasons(values)
    if cleaned:
        return "主要原因是：" + "；".join(cleaned[:3])
    return "主要原因是价格位置还没有回到更合适的买点。"


def execution_state_label(state: str | None) -> str:
    mapping = {
        "PLAN_READY": "计划区间内",
        "BUY_NOW": "计划区间内",
        "BREAKOUT_BUY": "计划区间内",
        "RECLAIM_BUY": "计划区间内",
        "AFTERNOON_RELAUNCH_BUY": "计划区间内",
        "WAIT_PULLBACK": "更适合等回踩",
        "WAIT_NEXT_SESSION": "更适合等回踩",
        "WATCH_ONLY": "暂不入场",
        "OBSERVE": "暂不入场",
        "RISK_HIGH": "风险偏高",
        "INVALIDATED": "已触发失效条件",
        "UNAVAILABLE": "暂不入场",
    }
    key = str(state or "").strip().upper()
    return mapping.get(key, key or "暂不入场")
