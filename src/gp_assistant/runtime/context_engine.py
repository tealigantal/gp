from __future__ import annotations

from typing import Any, Dict

from ..book.repo import load_run
from ..contracts.objects import MarketBook
from ..runtime.market_clock import compute_market_state


def _run_slice(run) -> Dict[str, Any]:
    if run is None:
        return {}
    return {
        "run_id": run.run_id,
        "trading_day": run.trading_day,
        "artifact_id": run.artifact_id,
        "market_phase": run.market_phase,
        "slot_status": run.slot_status,
        "run_action": run.run_action,
        "picks": [
            {
                "symbol": entry.symbol,
                "rank": entry.rank,
                "name": entry.name,
                "execution_state": entry.execution_state,
                "action": entry.action,
            }
            for entry in run.picks[:6]
        ],
    }


def build_context(memory_ctx: Dict[str, Any], book: MarketBook) -> Dict[str, Any]:
    session = memory_ctx["session"]
    turns = memory_ctx["recent_turns"]
    claims = memory_ctx["recent_claims"]
    active_run = load_run(session.active_run_id)
    previous_run = load_run(session.previous_run_id)
    market_state = compute_market_state()
    return {
        "session_has_active_run": bool(session.active_run_id),
        "session_focus_symbol": (session.focus_subject.get("symbol") if isinstance(session.focus_subject, dict) else None),
        "session": {
            "session_id": session.session_id,
            "active_run_id": session.active_run_id,
            "previous_run_id": session.previous_run_id,
            "focus_subject": session.focus_subject,
            "compare_set": session.compare_set,
            "user_preferences": session.user_preferences,
            "last_seen_book_version": session.last_seen_book_version,
            "last_focus_rank": session.last_focus_rank,
            "last_focus_symbol": session.last_focus_symbol,
        },
        "market": {
            "market_phase": book.market_phase or market_state.market_phase,
            "slot_status": book.slot_status,
            "is_intraday": str(book.market_phase or "").upper() in {"INTRADAY_AM", "INTRADAY_PM", "LUNCH_BREAK"},
            "publish_allowed": book.publish_allowed,
            "gate_state": book.gate.state,
            "tradeable": book.daybook.tradeable,
        },
        "active_run": _run_slice(active_run),
        "previous_run": _run_slice(previous_run),
        "recent_turns": [{"role": t.role, "content": t.content, "meta": t.meta} for t in turns[-8:]],
        "recent_claims": [
            {
                "subject_type": c.subject_type,
                "subject_id": c.subject_id,
                "predicate": c.predicate,
                "value": c.value,
            }
            for c in claims[:12]
        ],
        "book": {
            "trading_day": book.trading_day,
            "book_version": book.book_version,
            "artifact_id": book.artifact_id,
            "slot_id": book.slot_id,
            "slot_status": book.slot_status,
            "pulse_slot_at": book.pulse_slot_at,
            "market_phase": book.market_phase,
            "tradeable": book.daybook.tradeable,
            "reason": book.daybook.reason,
            "top_board": [
                {
                    "symbol": entry.symbol,
                    "rank": entry.rank,
                    "name": entry.name,
                    "style_label": entry.style_label,
                    "execution_state": entry.execution_state,
                    "summary": entry.summary,
                }
                for entry in book.board[:6]
            ],
        },
    }
