from types import SimpleNamespace

from gp_assistant.contracts.objects import (
    AdviceRun,
    BoardEntry,
    DayBook,
    EvidencePack,
    Judgment,
    MarketBook,
    SessionState,
    TurnFrame,
    AdvicePick,
)
from gp_assistant.judgment.engine import make_judgment
from gp_assistant.runtime.evidence_planner import plan_evidence
from gp_assistant.runtime.turn_loop import _resolve_subject_entry


def _mk_entry(sym: str, rank: int) -> BoardEntry:
    pick = AdvicePick(symbol=sym, rank=rank)
    return BoardEntry(
        symbol=sym,
        name=None,
        rank=rank,
        final_score=1.0,
        live_score=1.0,
        execution_state='actionable',
        can_open=True,
        stretched=False,
        invalidated=False,
        summary='x',
        style_label=None,
        pick=pick,
        pulse=None,
    )


def test_recommend_gated_under_postclose_pending():
    db = DayBook(trading_day='20240320', generated_at='2024-03-20T15:01:00')
    book = MarketBook(trading_day='20240320', book_version='b1', updated_at='2024-03-20T15:01:00', regime={}, daybook=db)
    book.market_phase = 'POSTCLOSE_PENDING'
    book.data_status = 'close_pending'
    session = SessionState(session_id='s', created_at='t', updated_at='t')
    frame = TurnFrame(frame_id='f', raw_message='今天给我3只', subject='run', request='recommend', freshness='current_book')
    ev = EvidencePack(frame=frame, session=session, book=book)
    j = make_judgment(session_id='s', frame=frame, evidence=ev)
    assert j.kind == 'no_trade'


def test_history_keyword_sets_need_previous_run():
    frame = TurnFrame(frame_id='f', raw_message='上一轮第二只为什么', subject='pick', request='explain', freshness='current_book')
    plan = plan_evidence(frame)
    assert plan['need_previous_run'] is True


def test_resolve_uses_previous_run_for_rank():
    # active picks
    active = [
        _mk_entry('600519', 1),
        _mk_entry('000001', 2),
    ]
    prev = [
        _mk_entry('000333', 1),
        _mk_entry('000002', 2),
    ]
    db = DayBook(trading_day='20240319', generated_at='t')
    book = MarketBook(trading_day='20240319', book_version='b', updated_at='t', regime={}, daybook=db)
    book.board = active
    session = SimpleNamespace(focus_subject={}, compare_set=[])
    frame = TurnFrame(frame_id='f', raw_message='上一轮第二只', subject='pick', request='explain', freshness='current_book', references={'rank': 2})
    prev_run = AdviceRun(run_id='r0', session_id='s', book_version='b0', created_at='t', trading_day='20240318', picks=prev)
    sub, comps = _resolve_subject_entry(frame, {'session': session}, book, SimpleNamespace(picks=active), prev_run)
    assert sub is not None and sub.symbol == '000002'
