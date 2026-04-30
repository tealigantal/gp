from __future__ import annotations

from typing import Any, Iterable, List, Optional

from ..core.config import load_config


def intraday_runtime_enabled() -> bool:
    return bool(getattr(load_config(), "intraday_runtime_enabled", False))


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
    lowered = text.lower()
    if lowered == "intraday_runtime_disabled":
        return "盘中 5 分钟执行数据已停用，当前只保留日线计划和观察结论。"
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
    return "主要原因是盘中闸门还没放行，或者价格位置还没有回到更合适的买点。"


def execution_state_label(state: str | None) -> str:
    mapping = {
        "BUY_NOW": "可以按计划执行",
        "BREAKOUT_BUY": "等待放量突破确认",
        "RECLAIM_BUY": "等待回踩确认",
        "AFTERNOON_RELAUNCH_BUY": "等待午后重新走强确认",
        "WAIT_PULLBACK": "更适合等回踩确认",
        "WAIT_NEXT_SESSION": "留到下一交易窗口再确认",
        "WATCH_ONLY": "暂时只观察",
        "OBSERVE": "暂时只观察",
        "RISK_HIGH": "风险偏高",
        "INVALIDATED": "已触发失效条件",
        "UNAVAILABLE": "执行数据暂不完整",
    }
    key = str(state or "").strip().upper()
    return mapping.get(key, key or "继续观察")
