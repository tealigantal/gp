from __future__ import annotations

import json

from gp_assistant.runtime.concern_parser import parse_concern
from gp_assistant.contracts.objects import MarketBook, DayBook, BoardEntry, AdvicePick


def _dummy_book() -> MarketBook:
    # Minimal viable MarketBook for context building
    pick = AdvicePick(symbol='600519', name='贵州茅台', rank=1, strategy_id='s01', thesis='')
    be = BoardEntry(
        symbol='600519', name='贵州茅台', rank=1, final_score=1.0, live_score=1.0,
        execution_state='watch', can_open=False, stretched=False, invalidated=False,
        summary='示例', style_label=None, pick=pick, pulse=None,
    )
    db = DayBook(trading_day='20260101', generated_at='2026-01-01T00:00:00Z')
    return MarketBook(
        trading_day='20260101', book_version='v1', updated_at='2026-01-01T00:00:00Z',
        daybook=db, board=[be], watchset=[], symbol_states={}, portfolio_snapshot={}, last_closed_5m=None,
        side_results=[], regime={},
    )


def _memory_ctx():
    # Minimal session-shaped object for context
    from gp_assistant.contracts.objects import SessionState
    from gp_assistant.runtime.utils import now_iso
    return {
        'session': SessionState(session_id='test', created_at=now_iso(), updated_at=now_iso()),
        'recent_turns': [],
        'recent_claims': [],
    }


def _mock_llm(monkeypatch, content_obj: dict):
    # Patch LLMClient to avoid network and return content_obj
    from gp_assistant.llm import client as client_mod
    from gp_assistant.llm import interpret as interpret_mod

    class DummyLLM:
        def available(self):
            return True, 'ok'

        def chat(self, messages, json_mode=False, **kwargs):
            return {
                'choices': [
                    {'message': {'content': json.dumps(content_obj, ensure_ascii=False)}}
                ]
            }

    dummy = lambda *a, **k: DummyLLM()
    monkeypatch.setattr(client_mod, 'LLMClient', dummy)
    monkeypatch.setattr(interpret_mod, 'LLMClient', DummyLLM)


def test_greeting_goes_to_chat(monkeypatch):
    _mock_llm(monkeypatch, {
        'subject': 'run',
        'request': 'chat',
        'freshness': 'current_book',
        'references': {}, 'constraints': {}, 'ambiguity': {'confidence': 0.9, 'notes': []},
    })
    frame = parse_concern(_memory_ctx(), _dummy_book(), '你好')
    assert frame.request == 'chat'


def test_recommend_request(monkeypatch):
    _mock_llm(monkeypatch, {
        'subject': 'run',
        'request': 'recommend',
        'freshness': 'current_book',
        'references': {}, 'constraints': {'topk': 3}, 'ambiguity': {'confidence': 0.8, 'notes': []},
    })
    frame = parse_concern(_memory_ctx(), _dummy_book(), '今天给我3只')
    assert frame.request == 'recommend'


def test_exit_request(monkeypatch):
    _mock_llm(monkeypatch, {
        'subject': 'symbol',
        'request': 'exit',
        'freshness': 'current_book',
        'references': {'symbol': '600519'}, 'constraints': {}, 'ambiguity': {'confidence': 0.7, 'notes': []},
    })
    frame = parse_concern(_memory_ctx(), _dummy_book(), '600519现在该不该卖')
    assert frame.request == 'exit' and frame.subject == 'symbol'
