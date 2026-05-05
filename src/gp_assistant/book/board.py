from __future__ import annotations

from typing import Dict, List

from ..contracts.objects import AdvicePick, BoardEntry, DayBook, SymbolPulse


def _summary_for_state(state: str) -> str:
    state = str(state or "").lower()
    if state == "invalidated":
        return "价格已经跌破失效条件，这个计划先取消。"
    if state in {"actionable", "plan_ready", "daily_ready"}:
        return "价格处在日线计划区间内，按买入区和失效位分批处理。"
    if state in {"wait_pullback", "waiting_pullback"}:
        return "逻辑仍在，但更适合等回踩买入区再处理。"
    if state == "extended":
        return "价格偏离买入区，当前追价风险偏高。"
    if state in {"below_support", "breakdown_risk"}:
        return "价格接近或跌破关键支撑，计划风险偏高。"
    return "日线计划暂不入场，等待价格回到更合适的位置。"


def _daily_state_from_pick(pick: AdvicePick) -> str:
    meta = dict(pick.meta or {})
    state = str(meta.get("execution_state") or "").strip().lower()
    if state:
        return state
    return "actionable" if bool(meta.get("actionable") is True) else "observe_only"


def _stop_from_pick(pick: AdvicePick):
    plan = pick.stop_plan or {}
    return plan.get("price") or plan.get("stop") or plan.get("level") or plan.get("invalidation")


def _take_from_pick(pick: AdvicePick) -> list:
    plan = pick.take_profit_plan or {}
    values = plan.get("targets") or plan.get("levels") or plan.get("take") or plan.get("prices") or []
    if isinstance(values, list):
        return list(values)
    return [values] if values not in {None, ""} else []


def _daily_pulse_from_pick(pick: AdvicePick, rank: int, total: int) -> SymbolPulse:
    state = _daily_state_from_pick(pick)
    rank_score = 1.0 if total <= 1 else 1.0 - float((rank - 1) / max(1, total - 1))
    can_open = state in {"actionable", "plan_ready", "daily_ready"}
    invalidated = state in {"invalidated", "below_support", "breakdown_risk"}
    extended = state == "extended"
    return SymbolPulse(
        symbol=pick.symbol,
        execution_state=state,
        action=("BUY" if state in {"actionable", "plan_ready", "daily_ready", "waiting_pullback", "wait_pullback"} else "WATCH"),
        can_open=can_open,
        live_score=float(pick.scores.get("final") or 0.0),
        daily_rank_score=rank_score,
        exec_score=(1.0 if can_open else 0.5 if state in {"waiting_pullback", "wait_pullback"} else 0.0),
        signal_type="daily_plan",
        entry_zone=dict(pick.entry_plan or {}),
        stop=_stop_from_pick(pick),
        take=_take_from_pick(pick),
        invalidated=invalidated,
        extended=extended,
        reason_codes=[*list((pick.meta or {}).get("reason_codes") or []), "daily_plan"],
    )


def build_board(
    daybook: DayBook,
    pulse_map: Dict[str, SymbolPulse],
    *,
    artifact_id: str | None = None,
    slot_id: str | None = None,
) -> List[BoardEntry]:
    entries: List[BoardEntry] = []
    total = max(1, len(daybook.picks[:10]))
    for idx, pick in enumerate(daybook.picks[:10], start=1):
        pulse = pulse_map.get(pick.symbol) or _daily_pulse_from_pick(pick, idx, total)
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
                vwap=None,
                orb30_high=None,
                orb30_low=None,
                rs_index=None,
                rs_industry=None,
                slot_rel_vol=None,
                summary=_summary_for_state(pulse.execution_state),
                reason_codes=list(pulse.reason_codes),
                artifact_id=artifact_id,
                slot_id=slot_id,
                style_label=pick.style_label,
                pick=pick.model_copy(deep=True),
                pulse=pulse,
            )
        )
    entries.sort(key=lambda entry: float(entry.final_score or 0.0), reverse=True)
    for idx, entry in enumerate(entries, start=1):
        entry.rank = idx
        entry.pick.rank = idx
    return entries
