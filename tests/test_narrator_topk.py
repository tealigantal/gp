from gp_assistant.contracts.objects import AdvicePick, AdviceRun, BoardEntry, DayBook, EvidencePack, Judgment, MarketBook, SessionState, TurnFrame
from gp_assistant.core.errors import APIError
from gp_assistant.runtime.canonical_artifact import build_canonical_run, build_no_trade_view
from gp_assistant.runtime.narrator import build_reply, build_structured_reply


def _mk_book_with_board(k=3, *, market_phase="INTRADAY_PM", slot_status="OK", publish_allowed=True):
    db = DayBook(trading_day="20240319", generated_at="2024-03-19T16:10:00", regime={}, tradeable=True)
    book = MarketBook(
        trading_day="20240319",
        book_version="v1",
        updated_at="2024-03-19T16:10:00",
        regime={},
        daybook=db,
        market_phase=market_phase,
        slot_status=slot_status,
        publish_allowed=publish_allowed,
        pulse_slot_at="2024-03-19 14:55:00",
    )
    picks = []
    for i in range(1, k + 1):
        sym = f"{i:06d}"
        ap = AdvicePick(
            symbol=sym,
            rank=i,
            thesis=f"{sym} thesis",
            why_selected=f"{sym} why",
            entry_plan={"price": 10.0 + i},
            stop_plan={"price": 9.5 + i},
            take_profit_plan={"targets": [10.6 + i]},
        )
        be = BoardEntry(
            symbol=sym,
            name=None,
            rank=i,
            final_score=0.9 - i * 0.01,
            live_score=0.8 - i * 0.01,
            execution_state="watch",
            can_open=(publish_allowed and i == 1),
            stretched=False,
            invalidated=False,
            summary="x",
            style_label=None,
            pick=ap,
            pulse=None,
        )
        picks.append(be)
    book.board = picks
    return book


def test_recommend_respects_requested_topk(monkeypatch):
    monkeypatch.setattr("gp_assistant.runtime.narrator.render_reply", lambda payload: "ok")
    book = _mk_book_with_board(k=4)
    run = AdviceRun(run_id="r1", session_id="s", book_version=book.book_version, created_at="t", trading_day="20240319", picks=book.board[:4])
    canonical_run = build_canonical_run(book=book, run=run, picks=run.picks)
    session = SessionState(session_id="s", created_at="t", updated_at="t")
    ev = EvidencePack(frame=TurnFrame(frame_id="f", raw_message="今天给我4只", subject="run", request="recommend", freshness="active_run"), session=session, book=book)
    j = Judgment(kind="recommend", summary="ok", run=run, canonical_run=canonical_run, compare_entries=run.picks)
    reply = build_reply(session_id="s", frame=ev.frame, evidence=ev, judgment=j)
    assert len(reply.message["picks"]) == 4
    assert len(reply.right_panel["top3"]) == 3


def test_postclose_recommend_text_mentions_next_session(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.runtime.narrator.render_reply",
        lambda payload: (_ for _ in ()).throw(APIError(status_code=503, message="LLM unavailable", detail={"reason": "missing"})),
    )
    book = _mk_book_with_board(k=2, market_phase="POSTCLOSE_PENDING", slot_status="DEGRADED", publish_allowed=False)
    run = AdviceRun(run_id="r1", session_id="s", book_version=book.book_version, created_at="t", trading_day="20240319", picks=book.board[:2])
    canonical_run = build_canonical_run(book=book, run=run, picks=run.picks)
    session = SessionState(session_id="s", created_at="t", updated_at="t")
    ev = EvidencePack(frame=TurnFrame(frame_id="f", raw_message="收盘了也给我三只", subject="run", request="recommend", freshness="next_session_plan"), session=session, book=book)
    j = Judgment(kind="recommend", summary="ok", run=run, canonical_run=canonical_run, compare_entries=run.picks)
    reply = build_reply(session_id="s", frame=ev.frame, evidence=ev, judgment=j)
    assert "下一交易窗口计划" in reply.text
    assert len(reply.message["picks"]) == 2


def test_no_trade_reply_uses_reason_and_recovery(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.runtime.narrator.render_reply",
        lambda payload: (_ for _ in ()).throw(APIError(status_code=503, message="LLM unavailable", detail={"reason": "missing"})),
    )
    book = _mk_book_with_board(k=0, publish_allowed=False)
    run = AdviceRun(run_id="r0", session_id="s", book_version=book.book_version, created_at="t", trading_day="20240319", picks=[])
    canonical_run = build_canonical_run(book=book, run=run, picks=[])
    no_trade = build_no_trade_view(canonical_run, book)
    session = SessionState(session_id="s", created_at="t", updated_at="t")
    ev = EvidencePack(frame=TurnFrame(frame_id="f", raw_message="今天是不是不太适合做", subject="market", request="no_trade_explain", freshness="active_run"), session=session, book=book)
    j = Judgment(kind="no_trade", summary=no_trade.status_reason, run=run, canonical_run=canonical_run, no_trade=no_trade)
    reply = build_reply(session_id="s", frame=ev.frame, evidence=ev, judgment=j)
    assert "恢复条件" in reply.text
    assert reply.message["message_kind"] == "no_trade"


def test_pick_detail_serenity_refs_are_target_only():
    book = _mk_book_with_board(k=2)
    for index, entry in enumerate(book.board, start=1):
        entry.explain_context["serenity"] = {
            "fact_ids": [f"serfact_{index}"],
            "status": "available",
        }
    run = AdviceRun(
        run_id="r-target",
        session_id="s",
        book_version=book.book_version,
        created_at="t",
        trading_day="20240319",
        picks=book.board,
    )
    canonical_run = build_canonical_run(book=book, run=run, picks=run.picks)
    session = SessionState(session_id="s", created_at="t", updated_at="t")
    evidence = EvidencePack(
        frame=TurnFrame(
            frame_id="f-target",
            raw_message="第一只为什么能进",
            subject="symbol",
            request="pick_detail",
            freshness="active_run",
        ),
        session=session,
        book=book,
    )
    judgment = Judgment(
        kind="pick_detail",
        summary="target",
        run=run,
        canonical_run=canonical_run,
        subject_entry=book.board[0],
    )
    reply = build_structured_reply("s", evidence, judgment, text="ok")
    assert reply.symbols == [book.board[0].symbol]
    assert "serfact_1" in reply.evidence_refs
    assert "serfact_2" not in reply.evidence_refs
