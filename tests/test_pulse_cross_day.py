import pandas as pd
from gp_assistant.contracts.objects import MarketBook, DayBook, AdvicePick, SymbolPulse
from gp_assistant.book.pulse5m import apply_pulse


def _mk_book_with_picks(day: str = '20240319') -> MarketBook:
    db = DayBook(trading_day=day, generated_at=f'{day}T16:10:00', regime={}, tradeable=True, picks=[
        AdvicePick(symbol='600519', rank=1),
        AdvicePick(symbol='000001', rank=2),
    ])
    return MarketBook(trading_day=day, book_version='v1', updated_at=f'{day}T16:10:00', regime={}, daybook=db)


def test_no_carry_over_yesterday_pulse_when_no_closed_bar():
    book = _mk_book_with_picks('20240319')
    # seed yesterday pulse to simulate existing state
    book.symbol_states['600519'] = SymbolPulse(symbol='600519', last_bar_at='2024-03-19T14:55:00', pulse_score=0.1,
                                               momentum_state='up', stretch_state='normal', liquidity_state='good',
                                               execution_state='observe', invalidated=False, trade_day='20240319', slot_at='2024-03-19 14:55:00')
    # next day 09:32 -> no closed bar yet
    out = apply_pulse(book, ['600519'], target_trade_day='20240320', target_slot_at=None)
    assert out.symbol_states['600519'].is_stale is True
    assert out.symbol_states['600519'].stale_reason == 'no_closed_bar_yet'
