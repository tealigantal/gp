from __future__ import annotations

from typing import Dict, List

from ..contracts.objects import BoardEntry, DayBook, SymbolPulse


def _base_entry_summary(pulse: SymbolPulse) -> str:
    state = str(pulse.execution_state or "").lower()
    if state == "invalidated":
        return "价格已经跌破失效条件，这个计划先取消。"
    if state == "breakout_buy":
        return "5 分钟突破 ORB30 且站上 VWAP，当前执行条件最强。"
    if state == "reclaim_buy":
        return "回踩买入区或 VWAP 后重新收回，接近计划内低风险入场。"
    if state == "afternoon_relaunch_buy":
        return "午后重新放量走强，但执行上仍要按午后仓位规则控制。"
    if state == "wait_pullback":
        return "逻辑仍在，但更适合等回踩买入区再确认。"
    if state == "extended":
        return "价格偏离买入区，当前追价风险偏高。"
    if state == "unavailable":
        return "盘中执行数据暂不完整，先保留观察计划。"
    return "逻辑保留，继续等待更清晰的执行信号。"


def build_board(
    daybook: DayBook,
    pulse_map: Dict[str, SymbolPulse],
    *,
    artifact_id: str | None = None,
    slot_id: str | None = None,
) -> List[BoardEntry]:
    entries: List[BoardEntry] = []
    for pick in daybook.picks[:10]:
        pulse = pulse_map.get(pick.symbol)
        if pulse is None:
            pulse = SymbolPulse(symbol=pick.symbol, execution_state="unavailable", action="WATCH", can_open=False)
        summary = _base_entry_summary(pulse)
        entries.append(
            BoardEntry(
                symbol=pick.symbol,
                name=pick.name,
                rank=pick.rank,
                final_score=float(pick.scores.get("final") or 0.0),
                live_score=float(pulse.live_score),
                daily_rank_score=float(pulse.daily_rank_score),
                exec_score=float(pulse.exec_score),
                action=pulse.action,
                execution_state=pulse.execution_state,
                can_open=bool(pulse.can_open),
                stretched=bool(pulse.extended),
                extended=bool(pulse.extended),
                invalidated=bool(pulse.invalidated),
                signal_type=pulse.signal_type,
                entry_zone=dict(pulse.entry_zone),
                stop=pulse.stop,
                take=list(pulse.take),
                vwap=pulse.vwap,
                orb30_high=pulse.orb30_high,
                orb30_low=pulse.orb30_low,
                rs_index=pulse.rs_index,
                rs_industry=pulse.rs_industry,
                slot_rel_vol=pulse.slot_rel_vol,
                summary=summary,
                reason_codes=list(pulse.reason_codes),
                artifact_id=artifact_id,
                slot_id=slot_id,
                style_label=pick.style_label,
                pick=pick.model_copy(deep=True),
                pulse=pulse,
            )
        )
    entries.sort(key=lambda entry: float(entry.live_score or 0.0), reverse=True)
    for idx, entry in enumerate(entries, start=1):
        entry.rank = idx
        entry.pick.rank = idx
    return entries
