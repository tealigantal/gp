from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str]
    replaced_text: str | None = None


_BANNED = [
    "买入价",
    "止损价",
    "触发价",
    "条件单",
    "突破",
    "元",
]


def validate_output(text: str) -> ValidationResult:
    errors: List[str] = []
    lower = text
    for k in _BANNED:
        if k in lower:
            errors.append(f"禁止出现价格/触发相关措辞：{k}")
    if "仅用于研究与教育" not in text:
        errors.append("缺少免责声明：需包含‘仅用于研究与教育’字样")
    ok = not errors
    replaced = None
    if not ok:
        replaced = "【安全输出模式】本输出触发合规拦截。仅用于研究与教育，不构成投资建议。"
    return ValidationResult(ok=ok, errors=errors, replaced_text=replaced)


def validate_pick_json(obj: Dict[str, Any]) -> ValidationResult:
    errors: List[str] = []
    top = obj.get("top", [])
    required_item_fields = {
        "symbol",
        "name",
        "sector",
        "indicators",
        "noise_level",
        "strategy_attribution",
        "backtest",
        "risk_constraints",
        "actions",
        "time_stop",
        "events",
    }
    for i, item in enumerate(top):
        miss = [k for k in required_item_fields if k not in item]
        if miss:
            errors.append(f"第{i+1}条缺少字段: {miss}")
    if not obj.get("disclaimer"):
        errors.append("缺少 disclaimer 字段")
    ok = not errors
    return ValidationResult(ok=ok, errors=errors, replaced_text=None)

