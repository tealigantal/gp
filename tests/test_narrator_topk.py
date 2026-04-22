from gp_assistant.contracts.objects import AdvicePick, BoardEntry, DayBook, MarketBook, EvidencePack, SessionState, Judgment, TurnFrame
from gp_assistant.runtime.narrator import build_reply


def _mk_book_with_board(k=5):
    db = DayBook(trading_day='20240319', generated_at='2024-03-19T16:10:00', regime={}, tradeable=True)
    m = MarketBook(trading_day='20240319', book_version='v1', updated_at='2024-03-19T16:10:00', regime={}, daybook=db)
    picks = []
    for i in range(1, k + 1):
        sym = f'{i:06d}'
        ap = AdvicePick(symbol=sym, rank=i)
        be = BoardEntry(symbol=sym, name=None, rank=i, final_score=1.0, live_score=1.0, execution_state='actionable', can_open=True, stretched=False, invalidated=False, summary='x', style_label=None, pick=ap, pulse=None)
        picks.append(be)
    m.board = picks
    return m


def test_recommend_respects_requested_topk():
    book = _mk_book_with_board(k=4)
    # emulate a run with topk=4
    run_picks = book.board[:4]
    run = type('Run', (), {'run_id': 'r1', 'book_version': book.book_version, 'picks': run_picks})
    session = SessionState(session_id='s', created_at='t', updated_at='t')
    ev = EvidencePack(frame=TurnFrame(frame_id='f', raw_message='今天给我4只', subject='run', request='recommend', freshness='current_book'), session=session, book=book)
    j = Judgment(kind='recommend', summary='ok', run=run, compare_entries=run_picks)
    reply = build_reply(session_id='s', frame=ev.frame, evidence=ev, judgment=j)
    assert len(reply.message['picks']) == 4
    assert len(reply.right_panel['top3']) == 4
