from __future__ import annotations

import pandas as pd

from gp_assistant.contracts.objects import (
    AdvicePick,
    AdviceRun,
    BoardEntry,
    DayBook,
    EvidencePack,
    MarketBook,
    SessionState,
    TurnFrame,
)
from gp_assistant.evidence.live_quote_service import build_live_quote_snapshot, extract_user_quote
from gp_assistant.judgment import workflow
from gp_assistant.runtime.utils import now_iso


def _entry(symbol: str = "601899") -> BoardEntry:
    pick = AdvicePick(
        symbol=symbol,
        name="紫金矿业",
        rank=2,
        strategy_id="S3",
        thesis="等待回踩",
        why_selected="结构仍在，但位置偏中上",
    )
    return BoardEntry(
        symbol=symbol,
        name="紫金矿业",
        rank=2,
        final_score=59.97,
        live_score=0.0,
        execution_state="waiting_pullback",
        can_open=False,
        stretched=False,
        invalidated=False,
        summary="等待回踩",
        pick=pick,
        recommendation_state="TRIGGER_PLAN",
        execution_plan={
            "trigger_price": 35.52,
            "entry_low": 33.24,
            "entry_high": 35.52,
            "stop_price": 33.24,
            "take1": 37.96,
            "take2": 39.10,
        },
        strategy_context={"champion_strategy": "S3", "champion_strategy_score": 0.36},
    )


def _book(entry: BoardEntry) -> MarketBook:
    daybook = DayBook(trading_day="20260512", generated_at=now_iso(), tradeable=True, picks=[entry.pick])
    return MarketBook(
        trading_day="20260512",
        book_version="book1",
        updated_at=now_iso(),
        daybook=daybook,
        board=[entry],
        market_phase="INTRADAY_AM",
        slot_status="OK",
        publish_allowed=True,
        pulse_trade_day="20260512",
    )


def _frame(raw: str) -> TurnFrame:
    return TurnFrame(
        frame_id="f1",
        raw_message=raw,
        subject="symbol",
        request="live_entry_check",
        freshness="active_run",
        references={"symbol": "601899"},
        constraints={},
        ambiguity={"confidence": 0.9, "notes": []},
    )


def _evidence(raw: str) -> EvidencePack:
    entry = _entry()
    book = _book(entry)
    run = AdviceRun(
        run_id="run1",
        session_id="s1",
        book_version=book.book_version,
        created_at=now_iso(),
        trading_day=book.trading_day,
        picks=[entry],
    )
    return EvidencePack(
        frame=_frame(raw),
        session=SessionState(session_id="s1", created_at=now_iso(), updated_at=now_iso()),
        book=book,
        active_run=run,
        subject_entry=entry,
    )


def test_extract_user_quote_from_intraday_price_text():
    quote = extract_user_quote("紫金矿业今天最高价35.33，现在是34.91，稳定了一段时间了")

    assert quote["current_price"] == 34.91
    assert quote["day_high"] == 35.33
    assert quote["stable_hint"] is True


def test_live_entry_uses_minute_quote_when_available(monkeypatch):
    monkeypatch.setattr(
        workflow,
        "build_live_quote_snapshot",
        lambda **_: {
            "source": "akshare:minute_1m",
            "verified": True,
            "latest_time": "2026-05-12 11:13:00",
            "current_price": 34.96,
            "day_high": 35.33,
            "day_low": 34.71,
            "average_price": 35.107,
            "user_quote": {"current_price": 34.90, "day_high": 35.33},
        },
    )

    judgment = workflow.live_entry_workflow(_evidence("601899 最高35.33，现在34.90，能不能入场"))
    live = judgment.live_entry

    assert live is not None
    assert live.quote_snapshot["source"] == "akshare:minute_1m"
    assert "已用分钟数据核验到 2026-05-12 11:13:00" in live.summary
    assert "最新价 34.96" in live.summary
    assert "计划区间 33.24 - 35.52" in live.summary
    assert "稳健等回踩" in live.summary


def test_live_entry_mentions_minute_user_quote_mismatch(monkeypatch):
    monkeypatch.setattr(
        workflow,
        "build_live_quote_snapshot",
        lambda **_: {
            "source": "akshare:minute_1m",
            "verified": True,
            "latest_time": "2026-05-12 11:13:00",
            "current_price": 35.20,
            "day_high": 35.33,
            "user_quote": {"current_price": 34.90, "day_high": 35.33},
            "user_quote_mismatch": True,
        },
    )

    judgment = workflow.live_entry_workflow(_evidence("601899 最高35.33，现在34.90，能不能入场"))
    live = judgment.live_entry

    assert live is not None
    assert "你给的现价 34.90 与分钟最新价 35.20 有差异" in live.summary


def test_live_entry_falls_back_to_user_quote_explicitly(monkeypatch):
    monkeypatch.setattr(
        workflow,
        "build_live_quote_snapshot",
        lambda **_: {
            "source": "user",
            "verified": False,
            "status": "user_quote_only",
            "current_price": 34.90,
            "day_high": 35.33,
            "user_quote": {"current_price": 34.90, "day_high": 35.33},
        },
    )

    judgment = workflow.live_entry_workflow(_evidence("601899 最高35.33，现在34.90，能不能入场"))
    live = judgment.live_entry

    assert live is not None
    assert live.quote_snapshot["source"] == "user"
    assert "未完成实时核验" in live.summary
    assert "仅按你给的价格判断" in live.summary
    assert "现价 34.90" in live.summary
    assert "没有突破触发价" in live.summary


class _FakeAkForMinuteRoute:
    def __init__(self) -> None:
        self.spot_called = False
        self.bid_ask_called = False

    def stock_zh_a_hist_min_em(self, *, symbol, start_date, end_date, period, adjust):
        assert symbol == "601899"
        assert start_date == "2026-05-12 09:30:00"
        assert end_date == "2026-05-12 15:00:00"
        assert period == "1"
        assert adjust == ""
        return pd.DataFrame(
            [
                {"时间": "2026-05-12 09:31:00", "收盘": 34.80, "最高": 34.92, "最低": 34.70, "均价": 34.81},
                {"时间": "2026-05-12 11:13:00", "收盘": 34.96, "最高": 35.33, "最低": 34.71, "均价": 35.10},
            ]
        )

    def stock_bid_ask_em(self, *, symbol):
        self.bid_ask_called = True
        raise AssertionError("bid/ask should not be called when minute succeeds")

    def stock_zh_a_spot_em(self):
        self.spot_called = True
        raise AssertionError("full-market snapshot must not be called")


class _FakeProviderForMinuteRoute:
    def __init__(self) -> None:
        self.ak = _FakeAkForMinuteRoute()

    def _import(self):
        return self.ak

    def _with_requests_timeout(self, fn):
        return fn()


def test_quote_service_uses_single_ticket_minute_route_without_full_market_snapshot():
    provider = _FakeProviderForMinuteRoute()

    quote = build_live_quote_snapshot(
        symbol="601899",
        user_message="601899 最高35.33，现在34.90，能不能入场",
        trade_day="20260512",
        provider=provider,
    )

    assert quote["source"] == "akshare:minute_1m"
    assert quote["latest_time"] == "2026-05-12 11:13:00"
    assert quote["current_price"] == 34.96
    assert quote["day_high"] == 35.33
    assert provider.ak.bid_ask_called is False
    assert provider.ak.spot_called is False


def test_quote_service_does_not_need_full_market_snapshot(monkeypatch):
    monkeypatch.setattr(
        "gp_assistant.evidence.live_quote_service._fetch_minute_quote",
        lambda *_, **__: (_ for _ in ()).throw(RuntimeError("minute down")),
    )
    monkeypatch.setattr(
        "gp_assistant.evidence.live_quote_service._fetch_bid_ask_quote",
        lambda *_, **__: (_ for _ in ()).throw(RuntimeError("bid ask down")),
    )

    quote = build_live_quote_snapshot(
        symbol="601899",
        user_message="601899 最高35.33，现在34.90，能不能入场",
        trade_day="20260512",
    )

    assert quote["source"] == "user"
    assert quote["current_price"] == 34.90
    assert quote["day_high"] == 35.33


def test_quote_service_retries_minute_once_before_degrading(monkeypatch):
    calls = {"minute": 0}

    def fail_minute(*_, **__):
        calls["minute"] += 1
        raise RuntimeError("minute down")

    monkeypatch.setattr("gp_assistant.evidence.live_quote_service._fetch_minute_quote", fail_minute)
    monkeypatch.setattr(
        "gp_assistant.evidence.live_quote_service._fetch_bid_ask_quote",
        lambda *_, **__: (_ for _ in ()).throw(RuntimeError("bid ask down")),
    )

    quote = build_live_quote_snapshot(
        symbol="601899",
        user_message="601899 最高35.33，现在34.90，能不能入场",
        trade_day="20260512",
    )

    assert calls["minute"] == 2
    assert quote["source"] == "user"
    assert quote["status"] == "user_quote_only"
