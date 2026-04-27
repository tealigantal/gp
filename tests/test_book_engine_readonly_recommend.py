from gp_assistant.book import engine
from gp_assistant.contracts.objects import AdvicePick, DayBook


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
    )


def test_load_current_book_builds_readonly_candidates_from_daybook(monkeypatch):
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

    book = engine.load_current_book()
    assert book is not None
    assert book.slot_status == 'UNAVAILABLE'
    assert book.publish_allowed is False
    assert [entry.symbol for entry in book.board] == ['600519', '000001']
    assert all(entry.action == 'INVALID' for entry in book.board)


def test_load_current_book_can_use_latest_saved_book_when_daybook_missing(monkeypatch):
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

    book = engine.load_current_book()
    assert book is not None
    assert book.daybook.trading_day == '20240320'
    assert len(book.board) == 2
