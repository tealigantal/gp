from __future__ import annotations

from gp_assistant.contracts.objects import DayBook, EvidencePack, MarketBook, SessionState, TurnFrame
from gp_assistant.decision_engine.intelligence import synthesize_decision


def _evidence(*, request: str = "live_entry_check", subject: str = "symbol", raw_message: str = "能买吗") -> EvidencePack:
    book = MarketBook(
        trading_day="20240320",
        book_version="book1",
        updated_at="2024-03-20T10:00:00+08:00",
        regime={"grade": "B"},
        daybook=DayBook(trading_day="20240320", generated_at="2024-03-20T09:00:00+08:00", tradeable=True),
        board=[],
        watchset=[],
        symbol_states={},
        portfolio_snapshot={},
        market_phase="INTRADAY_PM",
        slot_status="OK",
        publish_allowed=True,
    )
    frame = TurnFrame(frame_id="f", raw_message=raw_message, subject=subject, request=request, freshness="active_run")
    session = SessionState(session_id="s1", created_at="t", updated_at="t")
    return EvidencePack(frame=frame, session=session, book=book)


def _pick(**overrides):
    base = {
        "symbol": "600519",
        "name": "测试股份",
        "rank": 1,
        "execution_state": "PLAN_READY",
        "recommendation_state": "TRADING_SIGNAL",
        "can_execute_now": True,
        "thesis": "趋势延续，回踩质量较好。",
        "why_selected": "market-memory evidence supports this setup.",
        "entry_text": "10.00-10.30",
        "stop_text": "9.80",
        "take_text": "10.80",
        "probability": {
            "up_probability_3d": 0.66,
            "expected_return_3d": 0.032,
            "drawdown_probability": 0.16,
            "confidence": 0.72,
            "uncertainty": 0.12,
            "evidence": {"sample_size": 326, "effective_sample_size": 87, "mean_similarity": 0.82},
        },
        "risk": {"drawdown_probability": 0.16, "risk_flags": []},
        "ranking": {"ranking_score": 0.58},
        "historical_cases": [{"event_id": "e1", "similarity": 0.91}],
        "risk_flags": [],
    }
    base.update(overrides)
    return base


def test_open_decision_strengthened_thesis_can_add():
    result = synthesize_decision(
        evidence=_evidence(request="live_entry_check", subject="symbol", raw_message="这只能买吗"),
        pick=_pick(),
        objective="open_or_add_position",
    )

    assert result["decision_action"] == "ADD"
    assert result["thesis_lifecycle"]["current_thesis_state"] == "thesis_strengthened"
    assert result["decision_context_model"]["objective"] == "open_or_add_position"


def test_position_below_stop_invalidates_thesis_and_exits():
    result = synthesize_decision(
        evidence=_evidence(request="exit_decision", subject="holding", raw_message="我已经买了，亏了怎么办"),
        pick=_pick(execution_state="PLAN_READY", can_execute_now=False),
        objective="manage_existing_position",
        extra_constraints={
            "position_context": "已买入，成本 10.2，现在跌破止损",
            "plan_position": {"below_stop": True},
        },
    )

    assert result["decision_action"] == "EXIT"
    assert result["thesis_lifecycle"]["current_thesis_state"] == "thesis_invalidated"
    assert "price_below_stop" in result["thesis_lifecycle"]["invalidation_triggers"]


def test_no_trade_without_security_context_stays_no_trade():
    result = synthesize_decision(
        evidence=_evidence(request="no_trade_explain", subject="market", raw_message="今天为什么不做"),
        pick=None,
        objective="evaluate_no_trade_decision",
    )

    assert result["decision_action"] == "NO_TRADE"
    assert result["decision_context_model"]["security_context"]["symbol"] is None


def test_weak_probability_for_new_trade_waits_instead_of_no_trade():
    result = synthesize_decision(
        evidence=_evidence(request="live_entry_check", subject="symbol", raw_message="还能买吗"),
        pick=_pick(
            can_execute_now=True,
            adaptive_action="WATCH",
            recommendation_strength="exploratory",
            probability={
                "up_probability_3d": 0.43,
                "expected_return_3d": -0.01,
                "drawdown_probability": 0.52,
                "confidence": 0.45,
                "uncertainty": 0.31,
            },
            risk={"drawdown_probability": 0.52, "risk_flags": ["risk_estimation_failure"]},
            risk_flags=["risk_estimation_failure"],
        ),
        objective="open_or_add_position",
    )

    assert result["decision_action"] == "WAIT"
    assert result["thesis_lifecycle"]["current_thesis_state"] == "thesis_weakening"
    assert result["decision_context_model"]["security_context"]["adaptive_action"] == "WATCH"


def test_open_decision_hard_block_stays_no_trade():
    result = synthesize_decision(
        evidence=_evidence(request="live_entry_check", subject="symbol", raw_message="还能买吗"),
        pick=_pick(hard_block=True, adaptive_action="ENTRY"),
        objective="open_or_add_position",
    )

    assert result["decision_action"] == "NO_TRADE"
    assert "security_hard_block" in result["thesis_lifecycle"]["invalidation_triggers"]
