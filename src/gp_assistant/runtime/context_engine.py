from __future__ import annotations

from typing import Any, Dict

from ..book.repo import load_run
from ..contracts.objects import MarketBook
from ..runtime.market_clock import compute_market_state


def _pick_plan_slice(entry) -> Dict[str, Any]:
    pick = getattr(entry, "pick", None)
    return {
        "symbol": getattr(entry, "symbol", None),
        "rank": getattr(entry, "rank", None),
        "name": getattr(entry, "name", None),
        "execution_state": getattr(entry, "execution_state", None),
        "recommendation_state": getattr(entry, "recommendation_state", None),
        "action": getattr(entry, "action", None),
        "entry_zone": getattr(entry, "entry_zone", None),
        "stop": getattr(entry, "stop", None),
        "take": getattr(entry, "take", None),
        "summary": getattr(entry, "summary", None),
        "entry_plan": getattr(pick, "entry_plan", {}) if pick else {},
        "stop_plan": getattr(pick, "stop_plan", {}) if pick else {},
        "take_profit_plan": getattr(pick, "take_profit_plan", {}) if pick else {},
        "thesis": getattr(pick, "thesis", None) if pick else None,
        "why_selected": getattr(pick, "why_selected", None) if pick else None,
        "champion_strategy": getattr(entry, "champion_strategy", None),
        "champion_strategy_score": getattr(entry, "champion_strategy_score", None),
        "score_breakdown": getattr(entry, "score_breakdown", {}),
        "strategy_context": getattr(entry, "strategy_context", {}),
        "risk_pack": getattr(entry, "risk_pack", {}),
        "explain_context": getattr(entry, "explain_context", {}),
    }


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
        "recommendation_state": getattr(run, "recommendation_state", None),
        "decision_evidence_pack": getattr(run, "decision_evidence_pack", {}),
        "picks": [_pick_plan_slice(entry) for entry in run.picks[:6]],
    }


def _structured_message_slice(turn) -> Dict[str, Any]:
    meta = dict(getattr(turn, "meta", {}) or {})
    message = meta.get("message") if isinstance(meta.get("message"), dict) else {}
    source: Dict[str, Any] = {
        "role": getattr(turn, "role", None),
        "content": getattr(turn, "content", None),
        "kind": meta.get("kind"),
        "run_id": meta.get("run_id"),
        "symbols": meta.get("symbols") or [],
        "message_kind": message.get("message_kind"),
        "symbol": message.get("symbol"),
        "narrative_text": message.get("narrative_text"),
    }
    for key in ("pick", "live_check", "exit_decision", "compare", "run", "picks"):
        value = message.get(key)
        if value:
            source[key] = value
    return source


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
        "recent_turns": [_structured_message_slice(t) for t in turns[-8:]],
        "recent_structured_messages": [
            _structured_message_slice(t)
            for t in turns[-8:]
            if getattr(t, "role", None) == "assistant" and isinstance((getattr(t, "meta", {}) or {}).get("message"), dict)
        ],
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
                {**_pick_plan_slice(entry), "style_label": entry.style_label}
                for entry in book.board[:6]
            ],
        },
    }
