from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..contracts.objects import MarketBook, SessionState
from ..core.config import load_config
from ..llm.semantics import SemanticTurnSignals, analyze_turn_semantics
from .market_clock import (
    compute_market_state,
    PHASE_NON_TRADING,
    PHASE_PREOPEN,
    PHASE_OPEN_NO_FIRST_BAR,
    PHASE_INTRADAY_AM,
    PHASE_LUNCH_BREAK,
    PHASE_INTRADAY_PM,
    PHASE_POSTCLOSE_PENDING,
)


def _intraday_runtime_enabled() -> bool:
    return bool(getattr(load_config(), "intraday_runtime_enabled", False))


@dataclass
class RefreshPlan:
    level: str  # L0 | L1 | L2 | L3
    scope: str  # none | subject_only | active_run | watchset
    target_daybook_effective_day: str
    target_pulse_trade_day: Optional[str]
    target_pulse_slot_at: Optional[str]
    market_phase: str
    data_status: str
    invalidate_active_run: bool = False
    reason_codes: List[str] = field(default_factory=list)
    # optional hint for minimal pulse set (best effort)
    symbols_hint: List[str] = field(default_factory=list)
    calendar_source: Optional[str] = None


def _extract_rank_from_zh(s: str) -> Optional[int]:
    s = (s or '').strip()
    mapping = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5}
    for zh, n in mapping.items():
        if f'第{zh}只' in s or f'第{zh}' in s:
            return n
    import re
    m = re.search(r'第\s*(\d{1,2})\s*只', s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def _session_semantic_slice(session: SessionState) -> Dict[str, Any]:
    return {
        "active_run_id": session.active_run_id,
        "previous_run_id": session.previous_run_id,
        "focus_subject": session.focus_subject,
        "last_focus_symbol": session.last_focus_symbol,
        "last_focus_rank": session.last_focus_rank,
    }


def _book_semantic_slice(book: Optional[MarketBook]) -> Dict[str, Any]:
    if book is None:
        return {}
    return {
        "trading_day": book.trading_day,
        "market_phase": book.market_phase,
        "slot_status": book.slot_status,
        "board": [
            {"symbol": getattr(entry, "symbol", None), "rank": getattr(entry, "rank", None), "name": getattr(entry, "name", None)}
            for entry in list(getattr(book, "board", []) or [])[:10]
        ],
    }


def _simple_preparse(
    user_message: str,
    *,
    session: SessionState,
    book: Optional[MarketBook],
    semantic_signals: Optional[SemanticTurnSignals] = None,
) -> Dict[str, Any]:
    msg = (user_message or "").strip()
    signals = semantic_signals or analyze_turn_semantics(
        user_message=msg,
        session=_session_semantic_slice(session),
        book=_book_semantic_slice(book),
    )
    history = bool(signals.history_mode)
    want_rebuild = signals.refresh_intent == "rebuild"
    want_live = signals.refresh_intent == "live"
    # parse symbols (6-digit A-share code naive)
    import re
    symbols: List[str] = []
    for s in re.findall(r"(?<!\d)(?:60|68|00|30)\d{4}(?!\d)", msg):
        if s not in symbols:
            symbols.append(s)
    if want_live and not symbols:
        fs = session.focus_subject.get("symbol") if isinstance(session.focus_subject, dict) and session.focus_subject.get("type") == "symbol" else None
        fs = fs or getattr(session, "last_focus_symbol", None)
        if isinstance(fs, str) and fs:
            symbols.append(fs)
    # Ordinal rank to board symbol
    rk = _extract_rank_from_zh(msg)
    if rk and not symbols and book is not None and getattr(book, 'board', None):
        try:
            for e in book.board:
                if int(getattr(e, 'rank', -1)) == int(rk):
                    symbols.append(e.symbol)
                    break
        except Exception:
            pass
    return {
        'history_mode': history,
        'want_rebuild': want_rebuild,
        'want_live': want_live,
        'symbols': symbols,
    }


def _decide_level(phase: str, want_rebuild: bool, want_live: bool) -> str:
    if phase == PHASE_POSTCLOSE_PENDING:
        return "L2"  # rebuild daybook target (data readiness handled by caller)
    if phase in {PHASE_NON_TRADING, PHASE_PREOPEN}:
        return "L2" if want_rebuild else "L0"
    if phase in {PHASE_OPEN_NO_FIRST_BAR, PHASE_INTRADAY_AM, PHASE_LUNCH_BREAK, PHASE_INTRADAY_PM}:
        if want_rebuild:
            return "L3"  # full
        return "L1" if want_live else "L0"
    return "L0"


def _decide_scope(symbols: List[str]) -> str:
    if not symbols:
        return "active_run"
    return "subject_only"


def _invalidate_active_run(
    session: SessionState,
    ms: Dict[str, Any],
    requires_live: bool,
) -> bool:
    # Compare session.active_run_* with targets if available
    try:
        t_day = ms['target_daybook_effective_day']
        t_pulse_day = ms.get('target_pulse_trade_day')
        t_slot = ms.get('target_pulse_slot_at')

        # If no active run, nothing to reuse
        if not session.active_run_id:
            return True

        # If session lacks metadata, be conservative across post-close boundary
        if not getattr(session, 'active_run_daybook_effective_day', None):
            # degrade: if post-close or today changed, invalidate
            if ms['market_phase'] == PHASE_POSTCLOSE_PENDING:
                return True
            return False

        if session.active_run_daybook_effective_day != t_day:
            return True
        if requires_live:
            if not t_pulse_day:
                # need live but no closed bar yet -> can't reuse live view
                return True
            if session.active_run_pulse_trade_day != t_pulse_day:
                return True
            # lexical compare slot timestamps; assume same format
            s_slot = session.active_run_pulse_slot_at or ""
            if not s_slot or (t_slot and s_slot < t_slot):
                return True
        return False
    except Exception:
        return True


def make_refresh_plan(
    *,
    session: SessionState,
    book: Optional[MarketBook],
    user_message: str,
    now: Optional[datetime] = None,
    semantic_signals: Optional[SemanticTurnSignals] = None,
) -> RefreshPlan:
    ms = compute_market_state(now)
    parsed = _simple_preparse(user_message, session=session, book=book, semantic_signals=semantic_signals)
    level = _decide_level(ms.market_phase, parsed['want_rebuild'], parsed['want_live'])
    if not _intraday_runtime_enabled():
        if level == "L1":
            level = "L0"
        elif level == "L3":
            level = "L2"
    scope = _decide_scope(parsed['symbols']) if level == 'L1' else ('watchset' if level in {'L2', 'L3'} else 'none')
    invalidate = _invalidate_active_run(session, ms.__dict__, requires_live=(level in {'L1', 'L3'}))
    reasons: List[str] = []
    if invalidate:
        reasons.append('invalidate_active_run')
    if ms.market_phase == PHASE_POSTCLOSE_PENDING:
        reasons.append('postclose_pending')
    if level == 'L1':
        reasons.append('pulse_only')
    if level in {'L2', 'L3'}:
        reasons.append('rebuild_daybook')

    return RefreshPlan(
        level=level,
        scope=scope,
        target_daybook_effective_day=ms.target_daybook_effective_day,
        target_pulse_trade_day=ms.target_pulse_trade_day,
        target_pulse_slot_at=ms.target_pulse_slot_at,
        market_phase=ms.market_phase,
        data_status=ms.data_status,
        invalidate_active_run=invalidate,
        reason_codes=reasons,
        symbols_hint=parsed['symbols'][:3],
        calendar_source=ms.calendar_source,
    )


def make_dashboard_refresh_plan(now: Optional[datetime] = None) -> RefreshPlan:
    """Build a conservative refresh plan for dashboard/book endpoint.

    - Daily mode: L2 rebuild daybook to the target completed day.
    """
    ms = compute_market_state(now)
    level = 'L2'
    scope = 'watchset'
    return RefreshPlan(
        level=level,
        scope=scope,
        target_daybook_effective_day=ms.target_daybook_effective_day,
        target_pulse_trade_day=None,
        target_pulse_slot_at=None,
        market_phase=ms.market_phase,
        data_status=ms.data_status,
        invalidate_active_run=False,
        reason_codes=['dashboard'],
        symbols_hint=[],
        calendar_source=ms.calendar_source,
    )


def make_postclose_pending_plan(book: Optional[MarketBook], now: Optional[datetime] = None) -> RefreshPlan:
    """Build a degraded plan for post-close when EOD not ready.

    Keep existing daybook_effective_day (previous completed day), mark phase and
    data_status, and do not publish new runs.
    """
    ms = compute_market_state(now)
    prev_day = None
    try:
        if book and getattr(book, 'daybook_effective_day', None):
            prev_day = book.daybook_effective_day
        elif book:
            prev_day = getattr(book.daybook, 'trading_day', None) or book.trading_day
    except Exception:
        prev_day = None
    # fallback: if no book, step back one day from target
    if not prev_day:
        prev_day = ms.target_daybook_effective_day
    return RefreshPlan(
        level='L0',
        scope='none',
        target_daybook_effective_day=str(prev_day),
        target_pulse_trade_day=None,
        target_pulse_slot_at=None,
        market_phase=PHASE_POSTCLOSE_PENDING,
        data_status='close_pending',
        invalidate_active_run=True,
        reason_codes=['postclose_pending'],
        symbols_hint=[],
        calendar_source=ms.calendar_source,
    )
