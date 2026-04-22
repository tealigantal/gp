from __future__ import annotations

from gp_assistant.book.daybook import _map_pick


def test_daybook_mapping_uses_user_fields_not_debug():
    item = {
        'symbol': '600519',
        'name': '贵州茅台',
        'user_thesis': '结构候选靠前，观察等待更优位置。',
        'why_selected_text': '相对同组候选综合条件更优。',
        'thesis': 'FALLBACK',
        'explain': 'DEBUG SHOULD NOT LEAK',
        'trade_plan': {'diagnostics': {}},
        'final_score': 0.9,
        'candidate_score': 0.8,
        'risk_flags': [],
        'champion': {'strategy': 's01', 'score': 0.5},
    }
    p = _map_pick(1, item)
    assert p.thesis == item['user_thesis']
    assert p.why_selected == item['why_selected_text']
    # ensure debug explain not used
    assert 'DEBUG' not in (p.thesis or '')

