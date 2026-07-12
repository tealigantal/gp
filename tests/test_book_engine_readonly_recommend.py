from gp_assistant.book import engine
from gp_assistant.contracts.objects import AdvicePick, DayBook
from gp_assistant.runtime.producer import producer_metadata


def _daybook() -> DayBook:
    return DayBook(
        trading_day='20240320',
        generated_at='2024-03-20T08:55:00+08:00',
        tradeable=False,
        picks=[
            AdvicePick(symbol='600519', rank=1),
            AdvicePick(symbol='000001', rank=2),
        ],
        reserve_picks=[AdvicePick(symbol='000333', rank=3)],
        reserve_symbols=['000333'],
        producer=producer_metadata(),
    )


def test_load_current_book_does_not_masquerade_daybook_as_current(monkeypatch):
    daybook = _daybook()

    class _State:
        target_daybook_effective_day = '20240320'
        target_pulse_trade_day = '20240320'
        target_pulse_slot_at = None
        market_phase = 'PREOPEN'
        data_status = 'unavailable'

    monkeypatch.setattr(engine, '_load_current_book', lambda: None)
    monkeypatch.setattr(engine, 'compute_market_state', lambda: _State())
    monkeypatch.setattr(engine, 'load_daybook', lambda trade_day: daybook if trade_day == '20240320' else None)
    monkeypatch.setattr(engine, 'load_latest_saved_book', lambda trade_day=None: None)
    monkeypatch.setattr(engine, 'load_latest_daybook', lambda: None)

    assert engine.load_current_book() is None


def test_load_current_book_does_not_use_latest_saved_book_as_current(monkeypatch):
    source = engine.build_unavailable_market_book(
        daybook=_daybook(),
        book_version='book_20240320_saved',
        market_phase='INTRADAY_PM',
        trade_day='20240320',
        slot_at='2024-03-20 14:05:00',
        reason='saved_book',
        data_status='ok',
    )

    class _State:
        target_daybook_effective_day = '20240320'
        target_pulse_trade_day = '20240320'
        target_pulse_slot_at = None
        market_phase = 'NON_TRADING'
        data_status = 'ok'

    monkeypatch.setattr(engine, '_load_current_book', lambda: None)
    monkeypatch.setattr(engine, 'compute_market_state', lambda: _State())
    monkeypatch.setattr(engine, 'load_daybook', lambda trade_day: None)
    monkeypatch.setattr(engine, 'load_latest_saved_book', lambda trade_day=None: source)
    monkeypatch.setattr(engine, 'load_latest_daybook', lambda: None)

    assert engine.load_current_book() is None
