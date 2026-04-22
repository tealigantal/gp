from __future__ import annotations

from typing import Any, Dict

from ..contracts.objects import MarketBook


def build_context(memory_ctx: Dict[str, Any], book: MarketBook) -> Dict[str, Any]:
    session = memory_ctx['session']
    turns = memory_ctx['recent_turns']
    claims = memory_ctx['recent_claims']
    return {
        'session_has_active_run': bool(session.active_run_id),
        'session_focus_symbol': (session.focus_subject.get('symbol') if isinstance(session.focus_subject, dict) else None),
        'session': {
            'session_id': session.session_id,
            'active_run_id': session.active_run_id,
            'previous_run_id': session.previous_run_id,
            'focus_subject': session.focus_subject,
            'compare_set': session.compare_set,
            'user_preferences': session.user_preferences,
            'last_seen_book_version': session.last_seen_book_version,
        },
        'recent_turns': [
            {'role': t.role, 'content': t.content, 'meta': t.meta} for t in turns[-8:]
        ],
        'recent_claims': [
            {'subject_type': c.subject_type, 'subject_id': c.subject_id, 'predicate': c.predicate, 'value': c.value} for c in claims[:12]
        ],
        'book': {
            'trading_day': book.trading_day,
            'book_version': book.book_version,
            'tradeable': book.daybook.tradeable,
            'reason': book.daybook.reason,
            'top_board': [
                {
                    'symbol': e.symbol,
                    'rank': e.rank,
                    'style_label': e.style_label,
                    'execution_state': e.execution_state,
                    'summary': e.summary,
                }
                for e in book.board[:6]
            ],
        },
    }
