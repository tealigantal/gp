from types import SimpleNamespace

from gp_assistant.contracts.objects import AdvicePick, BoardEntry, DayBook, MarketBook
from gp_assistant.runtime.reference_resolver import resolve_subject_and_compare


def _mk_board(symbols: list[str]):
    entries = []
    for i, s in enumerate(symbols, start=1):
        pick = AdvicePick(symbol=s, rank=i)
        entries.append(BoardEntry(
            symbol=s,
            name=None,
            rank=i,
            final_score=1.0,
            live_score=1.0,
            execution_state='observe',
            can_open=False,
            stretched=False,
            invalidated=False,
            summary='x',
            style_label=None,
            pick=pick,
            pulse=None,
        ))
    return entries


def _mk_book(symbols: list[str]) -> MarketBook:
    db = DayBook(trading_day='20240319', generated_at='2024-03-19T16:10:00', regime={}, tradeable=False)
    m = MarketBook(trading_day='20240319', book_version='v1', updated_at='2024-03-19T16:10:00', regime={}, daybook=db)
    m.board = _mk_board(symbols)
    return m


def test_compare_symbols_reference_resolution():
    book = _mk_book(['600519', '000001', '000333'])
    session = SimpleNamespace(focus_subject={}, compare_set=['600519', '000001'])
    frame = SimpleNamespace(references={'compare_symbols': ['600519', '000001']})
    subject, comps = resolve_subject_and_compare(frame=frame, session=session, book=book, active_entries=book.board)
    assert subject is None
    assert [e.symbol for e in comps] == ['600519', '000001']


def test_rank_reference_second_pick():
    book = _mk_book(['600519', '000001'])
    session = SimpleNamespace(focus_subject={}, compare_set=[])
    frame = SimpleNamespace(references={'rank': 2})
    subject, comps = resolve_subject_and_compare(frame=frame, session=session, book=book, active_entries=book.board)
    assert subject is not None and subject.symbol == '000001'
