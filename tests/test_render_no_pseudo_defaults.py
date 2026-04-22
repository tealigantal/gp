from __future__ import annotations

from gp_assistant.chat_compat import render as rnd


def test_render_missing_values_show_na_not_zeros():
    payload = {
        'as_of': '2099-01-01',
        'themes': [{'name': '娑撳顣紸', 'strength': ''}],  # empty strength -> no parentheses
        'picks': [
            {'symbol': 'AAA', 'trade_plan': {'bands': {}}, 'last_close': None},
            {'symbol': 'BBB', 'trade_plan': {'bands': {'S1': 0.0, 'R1': 0.0}}, 'last_close': 0.0},
        ],
        'debug': {'dropped_picks': [{'symbol': 'CCC', 'reason': 'strict_dropped'}]},
        'data_status': {'snapshot': {'ok': False, 'source': None, 'cache': 'none'}},
    }

    txt = rnd.render_recommendation_narrative(payload)
    # must show N/A markers and no 0.00 defaults
    assert 'N/A' in txt
    assert '0.00' not in txt
    # empty strength must not produce ()
    assert '()' not in txt
    # strict dropped note
    assert 'strict 娑撱垹绱? in txt
