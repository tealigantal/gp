from gp_assistant.selection_engine.strict_output import normalize_payload
from gp_assistant.core.strict import is_strict


def test_strict_drops_picks_without_last_close_or_bands(monkeypatch):
    # force strict
    monkeypatch.setenv('GP_STRICT_OUTPUT', '1')

    payload = {
        'as_of': '2099-01-01',
        'picks': [
            {'symbol': 'AAA', 'trade_plan': {'bands': {}}, 'last_close': None},
            {'symbol': 'BBB', 'trade_plan': {'bands': {'S1': 0.0, 'R1': 0.0}}, 'last_close': 0.0},
            {'symbol': 'CCC', 'trade_plan': {'bands': {'S1': 10.0, 'R1': 12.0}}, 'last_close': 11.0},
        ],
        'debug': {}
    }

    out = normalize_payload(payload)
    assert isinstance(out.get('picks'), list)
    # only CCC remains
    syms = [it['symbol'] for it in out['picks']]
    assert syms == ['CCC']
    # dropped reasons present
    dp = out.get('debug', {}).get('dropped_picks') or []
    assert any(d.get('symbol') == 'AAA' for d in dp)
    assert any(d.get('symbol') == 'BBB' for d in dp)
