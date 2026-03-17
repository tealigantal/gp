from __future__ import annotations

from gp_assistant.validation.paper_trade import start_tracking, update_with_bars, load_paperfolio


def test_paper_trade_lifecycle():
    # Setup
    start_tracking('RID:AAA', 'AAA', 'S', '2099-01-01', 10.0)
    # Two days of bars: day1 no hit, day2 target hit
    bars1 = [{"close": 10.1} for _ in range(5)]
    bars2 = [{"close": 10.6} for _ in range(5)]
    update_with_bars('AAA', bars1, entry_zone=[9.8, 10.2], stop=9.5, takes=[10.5])
    update_with_bars('AAA', bars2, entry_zone=[9.8, 10.2], stop=9.5, takes=[10.5])
    pf = load_paperfolio()
    picks = pf.get('picks') or []
    assert any(p.get('symbol')=='AAA' and p.get('entry_reached') for p in picks)
    assert any(p.get('symbol')=='AAA' and p.get('hit_take') for p in picks)
