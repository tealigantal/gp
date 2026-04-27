from __future__ import annotations

from ..contracts.objects import DayBook, LiveSlotArtifact, MarketBook, SlotDataQuality, SlotGate, SymbolPulse, TrackedUniverse
from ..runtime.market_clock import slot_id_for
from ..runtime.utils import gen_id, now_iso
from .board import build_board
from .side_results import detect_side_results


def tracked_universe_from_daybook(daybook: DayBook) -> TrackedUniverse:
    reco = [pick.symbol for pick in daybook.picks[:10] if pick.symbol]
    reserve = [pick.symbol for pick in daybook.reserve_picks[:2] if pick.symbol] or [symbol for symbol in daybook.reserve_symbols[:2] if symbol]
    total: list[str] = []
    seen: set[str] = set()
    for symbol in [*reco, *reserve]:
        clean = str(symbol).strip()
        if clean and clean not in seen:
            seen.add(clean)
            total.append(clean)
    return TrackedUniverse(reco=reco, reserve=reserve, portfolio=[], total=total)


def build_unavailable_pulses(
    daybook: DayBook,
    tracked_universe: TrackedUniverse,
    *,
    trade_day: str,
    slot_at: str | None,
    reason: str,
) -> dict[str, SymbolPulse]:
    ranked = [*daybook.picks, *daybook.reserve_picks]
    rank_map = {pick.symbol: idx + 1 for idx, pick in enumerate(ranked)}
    size = max(1, len(ranked))
    out: dict[str, SymbolPulse] = {}
    for symbol in tracked_universe.total:
        rank_score = 0.0
        if symbol in rank_map:
            rank_score = 1.0 if size == 1 else 1.0 - float((rank_map[symbol] - 1) / max(1, size - 1))
        out[symbol] = SymbolPulse(
            symbol=symbol,
            execution_state="unavailable",
            action="WATCH",
            can_open=False,
            live_score=100.0 * 0.62 * rank_score,
            daily_rank_score=rank_score,
            exec_score=0.0,
            signal_type="unavailable",
            entry_zone={},
            stop=None,
            take=[],
            reason_codes=[reason],
            trade_day=trade_day,
            slot_at=slot_at,
        )
    return out


def build_unavailable_artifact(
    *,
    daybook: DayBook,
    tracked_universe: TrackedUniverse,
    market_phase: str,
    trade_day: str,
    slot_at: str | None,
    portfolio_snapshot: dict,
    reason: str,
    previous_artifact: LiveSlotArtifact | None = None,
) -> LiveSlotArtifact:
    artifact_id = gen_id("slot")
    slot_id = slot_id_for(slot_at)
    pulses = build_unavailable_pulses(daybook, tracked_universe, trade_day=trade_day, slot_at=slot_at, reason=reason)
    board = build_board(daybook, pulses, artifact_id=artifact_id, slot_id=slot_id)
    old_map = {symbol: pulse.execution_state for symbol, pulse in (previous_artifact.symbol_states.items() if previous_artifact else [])}
    side_results = detect_side_results(old_map, board)
    return LiveSlotArtifact(
        artifact_id=artifact_id,
        slot_id=slot_id,
        trade_day=trade_day,
        slot_at=slot_at,
        market_phase=market_phase,
        slot_status="UNAVAILABLE",
        publish_allowed=False,
        daybook_effective_day=daybook.trading_day,
        gate=SlotGate(state="UNAVAILABLE", score=0.0, reasons=[reason]),
        tracked_universe=tracked_universe,
        board=board,
        symbol_states=pulses,
        data_quality=SlotDataQuality(
            snapshot_age_sec=None,
            symbols_expected=len(tracked_universe.total),
            symbols_received=0,
            benchmark_received=False,
            provider="akshare",
            complete=False,
            errors=[reason],
        ),
        portfolio_snapshot=portfolio_snapshot,
        provider_meta={"reason": reason},
        side_results=side_results,
        created_at=now_iso(),
        updated_at=now_iso(),
    )


def build_unavailable_market_book(
    *,
    daybook: DayBook,
    book_version: str,
    market_phase: str,
    trade_day: str,
    slot_at: str | None,
    reason: str,
    data_status: str = "unavailable",
) -> MarketBook:
    tracked_universe = tracked_universe_from_daybook(daybook)
    pulses = build_unavailable_pulses(daybook, tracked_universe, trade_day=trade_day, slot_at=slot_at, reason=reason)
    board = build_board(daybook, pulses, artifact_id=None, slot_id=slot_id_for(slot_at))
    return MarketBook(
        trading_day=daybook.trading_day,
        book_version=book_version,
        updated_at=now_iso(),
        regime=daybook.regime,
        daybook=daybook,
        board=board,
        watchset=list(tracked_universe.total),
        symbol_states=pulses,
        portfolio_snapshot={},
        side_results=[],
        artifact_id=None,
        slot_id=None,
        slot_status="UNAVAILABLE",
        publish_allowed=False,
        daybook_effective_day=daybook.trading_day,
        pulse_trade_day=trade_day,
        pulse_slot_at=slot_at,
        market_phase=market_phase,
        data_status=data_status,
        gate=SlotGate(state="UNAVAILABLE", score=0.0, reasons=[reason]),
        data_quality=SlotDataQuality(
            snapshot_age_sec=None,
            symbols_expected=len(tracked_universe.total),
            symbols_received=0,
            benchmark_received=False,
            provider="akshare",
            complete=False,
            errors=[reason],
        ),
        tracked_universe=tracked_universe,
    )
