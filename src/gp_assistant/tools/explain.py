# 简介：工具 - 解释器：将结构化推荐(单只/多只)转为可读说明与要点切片。
from __future__ import annotations

from typing import Any, Dict, List

from ..core.types import ToolResult


def _fmt_pct(x: float | None) -> str:
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:  # noqa: BLE001
        return "-"


def _explain_one(pick: Dict[str, Any]) -> Dict[str, Any]:
    sym = str(pick.get("symbol"))
    liq = pick.get("liquidity", {})
    inds = pick.get("indicators", {})
    stats = pick.get("stats", {})
    chip = pick.get("chip", {})
    flags = (pick.get("flags") or {})
    q = pick.get("q_grade", "Q?")
    theme = pick.get("theme", "")

    parts: List[str] = []
    parts.append(f"标的：{sym}（主题：{theme or '行业轮动'}，噪声等级：{q}）")
    # 面板
    try:
        liq_g = liq.get("grade") or "?"
        liq_amt = float(liq.get("avg5_amount", 0.0)) / 1e8  # 亿元
        panel = f"流动性≈{liq_amt:.2f}亿元({liq_g}) ATR%={_fmt_pct(inds.get('atr_pct'))} Gap={_fmt_pct(inds.get('gap_pct'))}"
    except Exception:  # noqa: BLE001
        panel = f"ATR%={_fmt_pct(inds.get('atr_pct'))} Gap={_fmt_pct(inds.get('gap_pct'))}"
    parts.append("面板：" + panel)
    # 统计
    parts.append(
        "统计："
        f"wr5={_fmt_pct(stats.get('win_rate_5'))} avg5={_fmt_pct(stats.get('avg_return_5'))} "
        f"mdd10≈{_fmt_pct(stats.get('mdd10_avg'))} 样本k={int(stats.get('k', 0))}"
    )
    # 筹码
    chip_line = f"筹码：90%带距上沿{_fmt_pct(chip.get('dist_to_90_high_pct'))}｜模式{chip.get('model_used','?')}｜置信度{chip.get('confidence','low')}"
    parts.append(chip_line)
    if flags.get("must_observe_only"):
        reasons = flags.get("reasons", ["风险约束触发"])
        parts.append("当日仅观察：" + "、".join(reasons))

    # 风控与动作（若存在 trade_plan 则引用，否则给默认口径）
    tp = pick.get("trade_plan", {})
    risk = tp.get("risk", {}) if isinstance(tp, dict) else {}
    stop_loss = str(risk.get("stop_loss", "收盘有效跌破支撑带"))
    time_stop = str(risk.get("time_stop", "第3日不强必走"))
    parts.append("风控：" + stop_loss + "；" + time_stop)

    return {
        "symbol": sym,
        "text": "；".join(parts),
        "highlights": {
            "wr5": stats.get("win_rate_5"),
            "avg5": stats.get("avg_return_5"),
            "atr_pct": inds.get("atr_pct"),
            "gap_pct": inds.get("gap_pct"),
            "q": q,
            "observe_only": bool(flags.get("must_observe_only", False)),
        },
    }


def run_explain(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    # 支持：pick=Dict 或 picks=List[Dict]
    pick = args.get("pick")
    picks = args.get("picks") or ([pick] if pick else [])
    if not picks:
        return ToolResult(ok=False, message="无可解释的标的")
    items = [_explain_one(p) for p in picks]
    text = "\n".join(it["text"] for it in items)
    return ToolResult(ok=True, message=f"已生成解释 {len(items)} 条", data={"items": items, "text": text})
