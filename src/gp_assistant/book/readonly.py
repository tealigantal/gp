from __future__ import annotations

from ..contracts.objects import DayBook, LiveSlotArtifact, MarketBook, SlotDataQuality, SlotGate, SymbolPulse, TrackedUniverse
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


def build_daily_plan_pulses(daybook: DayBook, tracked_universe: TrackedUniverse) -> dict[str, SymbolPulse]:
    board = build_board(daybook, {}, artifact_id=None, slot_id=None)
    out = {entry.symbol: entry.pulse for entry in board if entry.pulse is not None}
    for symbol in tracked_universe.total:
        if symbol not in out:
            out[symbol] = SymbolPulse(
                symbol=symbol,
                execution_state="observe_only",
                action="WATCH",
                can_open=False,
                signal_type="daily_plan",
                reason_codes=["daily_plan"],
            )
    return out


def build_daily_plan_artifact(
    *,
    daybook: DayBook,
    tracked_universe: TrackedUniverse,
    market_phase: str,
    trade_day: str,
    portfolio_snapshot: dict,
    previous_artifact: LiveSlotArtifact | None = None,
) -> LiveSlotArtifact:
    artifact_id = gen_id("daily")
    pulses = build_daily_plan_pulses(daybook, tracked_universe)
    board = build_board(daybook, pulses, artifact_id=artifact_id, slot_id=None)
    old_map = {symbol: pulse.execution_state for symbol, pulse in (previous_artifact.symbol_states.items() if previous_artifact else [])}
    side_results = detect_side_results(old_map, board)
    return LiveSlotArtifact(
        artifact_id=artifact_id,
        slot_id=None,
        trade_day=trade_day,
        slot_at=None,
        market_phase=market_phase,
        slot_status="OK",
        publish_allowed=bool(daybook.tradeable),
        daybook_effective_day=daybook.trading_day,
        gate=SlotGate(state="ALLOW", score=100.0, reasons=["daily_plan"]),
        tracked_universe=tracked_universe,
        board=board,
        symbol_states=pulses,
        data_quality=SlotDataQuality(
            snapshot_age_sec=None,
            symbols_expected=len(tracked_universe.total),
            symbols_received=len(tracked_universe.total),
            benchmark_received=True,
            provider="daily",
            complete=True,
            errors=[],
        ),
        portfolio_snapshot=portfolio_snapshot,
        provider_meta={"reason": "daily_plan"},
        side_results=side_results,
        created_at=now_iso(),
        updated_at=now_iso(),
    )


def build_daily_plan_market_book(
    *,
    daybook: DayBook,
    book_version: str,
    market_phase: str,
    trade_day: str,
    data_status: str = "daily_plan",
) -> MarketBook:
    tracked_universe = tracked_universe_from_daybook(daybook)
    pulses = build_daily_plan_pulses(daybook, tracked_universe)
    board = build_board(daybook, pulses, artifact_id=None, slot_id=None)
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
        slot_status="OK",
        publish_allowed=bool(daybook.tradeable),
        daybook_effective_day=daybook.trading_day,
        pulse_trade_day=None,
        pulse_slot_at=None,
        market_phase=market_phase,
        data_status=data_status,
        gate=SlotGate(state="ALLOW", score=100.0, reasons=["daily_plan"]),
        data_quality=SlotDataQuality(
            snapshot_age_sec=None,
            symbols_expected=len(tracked_universe.total),
            symbols_received=len(tracked_universe.total),
            benchmark_received=True,
            provider="daily",
            complete=True,
            errors=[],
        ),
        tracked_universe=tracked_universe,
    )


# Compatibility aliases for older call sites. These now return daily-plan artifacts, not unavailable pulse artifacts.
def build_unavailable_pulses(
    daybook: DayBook,
    tracked_universe: TrackedUniverse,
    *,
    trade_day: str,
    slot_at: str | None,
    reason: str,
) -> dict[str, SymbolPulse]:
    return build_daily_plan_pulses(daybook, tracked_universe)


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
    return build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked_universe,
        market_phase=market_phase,
        trade_day=trade_day,
        portfolio_snapshot=portfolio_snapshot,
        previous_artifact=previous_artifact,
    )


def build_unavailable_market_book(
    *,
    daybook: DayBook,
    book_version: str,
    market_phase: str,
    trade_day: str,
    slot_at: str | None,
    reason: str,
    data_status: str = "daily_plan",
) -> MarketBook:
    return build_daily_plan_market_book(
        daybook=daybook,
        book_version=book_version,
        market_phase=market_phase,
        trade_day=trade_day,
        data_status=data_status,
    )
