from __future__ import annotations

from types import SimpleNamespace

from gp_assistant.contracts.objects import (
    CanonicalRunArtifact,
    DayBook,
    MarketBook,
    SessionState,
    SlotDataQuality,
    SlotGate,
)
from gp_assistant.runtime.canonical_artifact import build_no_trade_view
from gp_assistant.runtime.concern_parser import parse_concern
from gp_assistant.runtime.turn_loop import _assistant_context_result
from gp_assistant.runtime.utils import now_iso


def _memory_ctx() -> dict:
    return {
        "session": SessionState(session_id="s1", created_at=now_iso(), updated_at=now_iso()),
        "recent_turns": [],
        "recent_claims": [],
    }


def _book() -> MarketBook:
    daybook = DayBook(trading_day="20260429", generated_at=now_iso(), reason="generated 10 picks")
    return MarketBook(
        trading_day="20260429",
        book_version="book_1",
        updated_at=now_iso(),
        daybook=daybook,
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        side_results=[],
        regime={},
        market_phase="POSTCLOSE_PENDING",
        slot_status="UNAVAILABLE",
        publish_allowed=False,
        gate=SlotGate(state="UNAVAILABLE", score=0.0, reasons=["intraday_runtime_disabled"]),
        data_quality=SlotDataQuality(
            snapshot_age_sec=None,
            symbols_expected=0,
            symbols_received=0,
            benchmark_received=False,
            provider="akshare",
            complete=False,
            errors=["intraday_runtime_disabled"],
        ),
    )


def test_term_explain_request_overrides_bad_llm_parse(monkeypatch):
    from gp_assistant.runtime import concern_parser

    monkeypatch.setattr(concern_parser, "load_config", lambda: SimpleNamespace(intraday_runtime_enabled=True))
    monkeypatch.setattr(
        concern_parser,
        "parse_turn_frame",
        lambda context, message: concern_parser.TurnFrame.model_validate(
            {
                "frame_id": "f1",
                "raw_message": message,
                "subject": "symbol",
                "request": "pick_detail",
                "freshness": "active_run",
                "references": {"symbol": "600111"},
                "constraints": {},
                "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
            }
        ),
    )

    frame = parse_concern(_memory_ctx(), _book(), "什么是收盘有效跌破支撑带")
    assert frame.request == "term_explain"


def test_live_request_downgrades_when_intraday_disabled(monkeypatch):
    from gp_assistant.runtime import concern_parser

    monkeypatch.setattr(concern_parser, "load_config", lambda: SimpleNamespace(intraday_runtime_enabled=False))
    monkeypatch.setattr(
        concern_parser,
        "parse_turn_frame",
        lambda context, message: concern_parser.TurnFrame.model_validate(
            {
                "frame_id": "f2",
                "raw_message": message,
                "subject": "symbol",
                "request": "live_entry_check",
                "freshness": "latest_5m",
                "references": {"symbol": "600111"},
                "constraints": {},
                "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
            }
        ),
    )

    frame = parse_concern(_memory_ctx(), _book(), "这只现在还能买吗")
    assert frame.request == "live_entry_check"
    assert frame.freshness == "active_run"


def test_no_trade_view_hides_internal_runtime_markers(monkeypatch):
    from gp_assistant.runtime import canonical_artifact

    monkeypatch.setattr(canonical_artifact, "load_config", lambda: SimpleNamespace(intraday_runtime_enabled=False))
    run = CanonicalRunArtifact(
        run_id="run_1",
        as_of=now_iso(),
        trading_day="20260429",
        run_action="NO_TRADE",
        non_trading=True,
        status_reason="当前不在连续竞价执行时段，以下为下一交易窗口计划。",
        no_trade_reasons=["generated 10 picks", "intraday_runtime_disabled", "日线数据未补齐到目标交易日：600111"],
        recovery_conditions=["下一交易窗口再用 5 分钟量价确认"],
        gate={},
        data_quality={},
        data_provenance={},
    )

    view = build_no_trade_view(run, _book())
    assert view.market_summary != "generated 10 picks"
    assert all("generated" not in item.lower() for item in view.no_trade_reasons)
    assert all(item != "intraday_runtime_disabled" for item in view.no_trade_reasons)
    assert view.recovery_conditions == []


def test_assistant_context_mentions_daily_mode_when_intraday_disabled(monkeypatch):
    from gp_assistant.runtime import turn_loop

    monkeypatch.setattr(turn_loop, "intraday_runtime_enabled", lambda: False)
    result = _assistant_context_result(_book())
    assert "盘中 5 分钟执行数据现在是停用的" in result.reply_text
    assert result.message["message_kind"] == "chat"
