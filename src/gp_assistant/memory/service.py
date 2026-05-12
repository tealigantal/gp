from __future__ import annotations

from typing import Any, Dict, List

from ..contracts.objects import TranscriptEvent, Judgment, ReplyBundle
from ..runtime.utils import gen_id, now_iso
from .session_store import load_session, save_session, list_sessions
from .transcript_store import append_event, next_seq, load_recent
from .claim_store import save_claims, load_recent_claims
from .preference_store import load_preferences, save_preferences


def load_memory_context(session_id: str) -> Dict[str, Any]:
    session = load_session(session_id)
    if not session.user_preferences:
        session.user_preferences = load_preferences(session_id)
    return {
        'session': session,
        'recent_turns': load_recent(session_id),
        'recent_claims': load_recent_claims(session_id),
    }


def commit_turn(session_id: str, user_message: str, reply: ReplyBundle, judgment: Judgment):
    session = load_session(session_id)
    turn_id = gen_id('turn')
    seq = next_seq(session_id)
    append_event(TranscriptEvent(
        seq=seq,
        turn_id=turn_id,
        session_id=session_id,
        role='user',
        content=user_message,
        created_at=now_iso(),
        meta={},
    ))
    append_event(TranscriptEvent(
        seq=seq + 1,
        turn_id=turn_id,
        session_id=session_id,
        role='assistant',
        content=reply.text,
        created_at=now_iso(),
        meta={
            'kind': reply.kind,
            'run_id': reply.run_id,
            'symbols': reply.symbols,
            'ui_items': reply.ui_items,
            'message': reply.message,
            'narrative_text': reply.text,
            'right_panel': reply.right_panel,
            'planner_trace': reply.planner_trace,
        },
    ))
    claims = [c.model_copy(update={'turn_id': turn_id, 'session_id': session_id}) for c in judgment.claims]
    save_claims(claims)
    session.last_turn_id = turn_id
    k = (judgment.kind or '').lower()
    if k != 'chat':
        if judgment.run is not None:
            session.previous_run_id = session.active_run_id
            session.active_run_id = judgment.run.run_id
            session.last_seen_book_version = judgment.run.book_version
            session.focus_subject = {'type': 'run', 'run_id': judgment.run.run_id}
            if judgment.run.picks:
                session.last_focus_symbol = judgment.run.picks[0].symbol
                try:
                    session.last_focus_rank = int(judgment.run.picks[0].rank)
                except Exception:
                    pass
            # snapshot run freshness metadata for reuse validation
            try:
                session.active_run_daybook_effective_day = judgment.run.daybook_effective_day
                session.active_run_pulse_trade_day = judgment.run.pulse_trade_day
                session.active_run_pulse_slot_at = judgment.run.pulse_slot_at
            except Exception:
                pass
        elif judgment.subject_entry is not None and k != 'run_change':
            session.focus_subject = {'type': 'symbol', 'symbol': judgment.subject_entry.symbol}
            session.last_focus_symbol = judgment.subject_entry.symbol
            try:
                session.last_focus_rank = int(judgment.subject_entry.rank)
            except Exception:
                pass
        elif judgment.single_stock_analysis is not None and k == 'single_stock_query':
            session.focus_subject = {'type': 'symbol', 'symbol': judgment.single_stock_analysis.symbol}
            session.last_focus_symbol = judgment.single_stock_analysis.symbol
            session.last_focus_rank = None
        if reply.symbols and k == 'compare':
            session.compare_set = list(reply.symbols[:3])
    session.last_claim_ids = [c.claim_id for c in claims][-20:]
    save_preferences(session_id, session.user_preferences)
    save_session(session)
    return session


def list_hot_symbols(limit: int = 20) -> List[str]:
    hot: List[str] = []
    seen: set[str] = set()
    for session in list_sessions(limit=limit):
        focus = session.focus_subject or {}
        sym = focus.get('symbol')
        if isinstance(sym, str) and sym and sym not in seen:
            seen.add(sym)
            hot.append(sym)
        for s in session.compare_set:
            if s and s not in seen:
                seen.add(s)
                hot.append(s)
    return hot[:limit]


def get_session_overview(session_id: str) -> Dict[str, Any]:
    ctx = load_memory_context(session_id)
    return {
        'session': ctx['session'].model_dump(),
        'recent_turns': [t.model_dump() for t in ctx['recent_turns']],
        'recent_claims': [c.model_dump() for c in ctx['recent_claims']],
    }
