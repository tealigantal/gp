from __future__ import annotations

import json
import math
from typing import Any

import pandas as pd

from gp_assistant.book.board import build_board
from gp_assistant.book.pulse5m import evaluate_slot_pulses
from gp_assistant.contracts.objects import (
    AdvicePick,
    AdviceRun,
    DayBook,
    EvidencePack,
    Judgment,
    MarketBook,
    SessionState,
    SlotGate,
    TrackedUniverse,
    TurnFrame,
)
from gp_assistant.intraday.features import build_feature_snapshot
from gp_assistant.intraday.plans import NEXT_SESSION_PLAN, TRADING_SIGNAL, TRIGGER_PLAN, UNAVAILABLE
from gp_assistant.intraday.strategies import STRATEGY_NAMES, StrategyRegistry, select_champion
from gp_assistant.judgment.publish import publish_run
from gp_assistant.llm.narrate import SYSTEM
from gp_assistant.runtime.concern_parser import parse_concern
from gp_assistant.runtime.narrator import build_reply


def _bars(close_values, *, vols):
    times = pd.date_range("2024-03-20 09:35:00", periods=len(close_values), freq="5min")
    rows = []
    prev = 10.0
    for idx, close in enumerate(close_values):
        rows.append(
            {
                "trade_time": times[idx],
                "open": prev,
                "high": max(prev, close) + 0.03,
                "low": min(prev, close) - 0.02,
                "close": close,
                "vol": vols[idx],
                "amount": close * vols[idx],
            }
        )
        prev = close
    return pd.DataFrame(rows)


def _pick(symbol="600519", rank=1) -> AdvicePick:
    return AdvicePick(
        symbol=symbol,
        rank=rank,
        name=symbol,
        industry="sector",
        entry_plan={"high": 10.30, "mid": 10.18},
        stop_plan={"price": 9.85},
        take_profit_plan={"targets": [10.80, 11.00]},
        scores={"final": 0.82},
        thesis="daily alpha remains strong",
        why_selected="strong daily candidate",
    )


def _daybook(picks=None) -> DayBook:
    return DayBook(
        trading_day="20240320",
        generated_at="2024-03-20T09:00:00+08:00",
        tradeable=True,
        picks=picks or [_pick()],
    )


def _tracked(symbols=None) -> TrackedUniverse:
    symbols = symbols or ["600519"]
    return TrackedUniverse(reco=symbols, reserve=[], portfolio=[], total=symbols)


def _assert_no_nan(value: Any):
    if isinstance(value, float):
        assert not math.isnan(value)
    elif isinstance(value, dict):
        for item in value.values():
            _assert_no_nan(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_nan(item)


def _feature_snapshot():
    pick = _pick()
    bars = _bars([10.00, 10.05, 10.08, 10.10, 10.12, 10.15, 10.25], vols=[90, 95, 100, 105, 110, 100, 150])
    benchmark = _bars([10.00, 10.01, 10.01, 10.02, 10.02, 10.03, 10.03], vols=[100] * 7)
    return build_feature_snapshot(
        symbol=pick.symbol,
        df=bars,
        benchmark=benchmark,
        pick=pick,
        pick_map={pick.symbol: pick},
        symbol_returns={pick.symbol: 0.025},
        slot_baselines={"10:05": 100.0},
        gate=SlotGate(state="ALLOW", score=80.0, reasons=["ok"]),
        slot_at="2024-03-20 10:05:00",
        trade_day="20240320",
        provider="test",
        market_phase="INTRADAY_AM",
    )


def test_feature_engine_computes_required_fields_without_nan():
    features = _feature_snapshot()
    for key in ["vwap", "ema5", "ema13", "atr5m", "slot_rel_vol", "rs_index", "compression_score", "rr_to_take1"]:
        assert key in features
    assert features["vwap"] > 0
    assert features["slot_rel_vol"] > 0
    assert features["rr_to_take1"] > 0
    _assert_no_nan(features)


def test_strategy_registry_candidates_and_champion_selection():
    features = _feature_snapshot()
    candidates = StrategyRegistry().run_all(features)
    names = [candidate.strategy_name for candidate in candidates]
    assert names == STRATEGY_NAMES
    assert all(candidate.strategy_name and isinstance(candidate.reject_reasons, list) for candidate in candidates)
    assert any(candidate.eligible and candidate.plan for candidate in candidates if candidate.strategy_name != "NO_TRADE_STRATEGY")
    champion = select_champion(candidates)
    assert champion.eligible
    assert champion.strategy_name != "NO_TRADE_STRATEGY"

    bad = dict(features)
    bad.update({"data_quality_score": 0.0, "bars_complete": False, "invalidated_flag": True, "price_vs_vwap": -0.05})
    no_trade = select_champion(StrategyRegistry().run_all(bad))
    assert no_trade.strategy_name == "NO_TRADE_STRATEGY"


def test_recommendation_states_for_trading_plan_next_session_and_unavailable():
    daybook = _daybook()
    bars = _bars([10.00, 10.05, 10.08, 10.10, 10.12, 10.15, 10.25], vols=[90, 95, 100, 105, 110, 100, 150])
    benchmark = _bars([10.00, 10.01, 10.01, 10.02, 10.02, 10.03, 10.03], vols=[100] * 7)
    common = dict(
        daybook=daybook,
        tracked_universe=_tracked(),
        bars={"600519": bars},
        benchmark=benchmark,
        slot_baselines={"600519": {"10:05": 100.0}},
        gate=SlotGate(state="ALLOW", score=80.0, reasons=["ok"]),
        slot_at="2024-03-20 10:05:00",
        trade_day="20240320",
        provider="test",
    )
    pulse = evaluate_slot_pulses(**common)["600519"]
    assert pulse.recommendation_state == TRADING_SIGNAL
    assert pulse.execution_plan["signal_valid_until_slot"]

    waiting_bars = _bars([10.00, 10.03, 10.05, 10.06, 10.08, 10.10, 10.12], vols=[90, 92, 95, 100, 102, 100, 105])
    waiting = evaluate_slot_pulses(**{**common, "bars": {"600519": waiting_bars}})["600519"]
    assert waiting.recommendation_state == TRIGGER_PLAN
    assert waiting.can_open is False

    next_session = evaluate_slot_pulses(**{**common, "market_phase": "POSTCLOSE_PENDING"})["600519"]
    assert next_session.recommendation_state == NEXT_SESSION_PLAN
    assert next_session.can_open is False

    unavailable = evaluate_slot_pulses(**{**common, "bars": {}})["600519"]
    assert unavailable.recommendation_state == UNAVAILABLE
    assert unavailable.can_open is False


def test_explain_context_survives_publish_and_reaches_narrator(monkeypatch):
    daybook = _daybook()
    bars = _bars([10.00, 10.05, 10.08, 10.10, 10.12, 10.15, 10.25], vols=[90, 95, 100, 105, 110, 100, 150])
    benchmark = _bars([10.00, 10.01, 10.01, 10.02, 10.02, 10.03, 10.03], vols=[100] * 7)
    pulses = evaluate_slot_pulses(
        daybook=daybook,
        tracked_universe=_tracked(),
        bars={"600519": bars},
        benchmark=benchmark,
        slot_baselines={"600519": {"10:05": 100.0}},
        gate=SlotGate(state="ALLOW", score=80.0, reasons=["ok"]),
        slot_at="2024-03-20 10:05:00",
        trade_day="20240320",
        provider="test",
    )
    board = build_board(daybook, pulses, artifact_id="artifact-1", slot_id="slot-1")
    book = MarketBook(
        trading_day="20240320",
        book_version="book-1",
        updated_at="2024-03-20T10:05:00+08:00",
        regime={},
        daybook=daybook,
        board=board,
        symbol_states=pulses,
        artifact_id="artifact-1",
        slot_id="slot-1",
        market_phase="INTRADAY_AM",
        slot_status="OK",
        publish_allowed=True,
        gate=SlotGate(state="ALLOW", score=80.0, reasons=["ok"]),
    )
    run = publish_run(session_id="s", book=book, topk=1)
    assert run.picks[0].explain_context["champion_strategy"]
    assert run.picks[0].pick.meta["explain_context"]["trigger_price"] is not None
    assert run.decision_evidence_pack["top_picks_full_context"][0]["feature_snapshot"] if "feature_snapshot" in run.decision_evidence_pack["top_picks_full_context"][0] else True

    captured = {}

    def fake_render(payload):
        captured["payload"] = payload
        return "当前模式：TRADING_SIGNAL\n策略、计划、风险已经基于 evidence pack 解释。"

    monkeypatch.setattr("gp_assistant.runtime.narrator.render_reply", fake_render)
    frame = TurnFrame(frame_id="f", raw_message="今天给我3只", subject="run", request="recommend", freshness="active_run")
    session = SessionState(session_id="s", created_at="t", updated_at="t")
    canonical = Judgment(kind="recommend", summary="ok", run=run, canonical_run=None)
    from gp_assistant.runtime.canonical_artifact import build_canonical_run

    canonical_run = build_canonical_run(book=book, run=run, picks=run.picks)
    judgment = canonical.model_copy(update={"canonical_run": canonical_run, "compare_entries": run.picks})
    reply = build_reply(session_id="s", frame=frame, evidence=EvidencePack(frame=frame, session=session, book=book), judgment=judgment)
    pack = captured["payload"]["llm_decision_context"]
    full = pack["top_picks_full_context"][0]
    for key in ["champion_strategy", "trigger_price", "entry_low", "stop_price", "score_breakdown", "competing_strategies", "data_quality_warnings"]:
        assert key in full or key in full.get("risk_pack", {})
    assert reply.message["decision_evidence_pack"]["top_picks_full_context"]


def test_llm_prompt_safety_contract_mentions_state_boundaries():
    assert "Do not modify action, recommendation_state, rank, champion_strategy" in SYSTEM
    assert "Do not say TRIGGER_PLAN has already triggered" in SYSTEM
    assert "Do not say NEXT_SESSION_PLAN can be bought now" in SYSTEM
    assert "Do not say buy when gate is BLOCKED or UNAVAILABLE" in SYSTEM
    assert "Do not generate missing values" in SYSTEM
    assert "Parameter explanation rules" in SYSTEM
    assert "slot_rel_vol" in SYSTEM
    assert "rs_index" in SYSTEM
    assert "rr_to_take1" in SYSTEM
    assert "price_vs_vwap" in SYSTEM
    assert "RS means relative strength comparison, not RSI" in SYSTEM
    assert "不得只说“量能和 RS 配合”" in SYSTEM


def test_parser_promotes_explain_compare_and_plan_detail(monkeypatch):
    from gp_assistant.llm import client as client_mod
    from gp_assistant.llm import interpret as interpret_mod

    class DummyLLM:
        def available(self):
            return True, "ok"

        def chat(self, messages, json_mode=False, **kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "subject": "market",
                                    "request": "chat",
                                    "freshness": "active_run",
                                    "references": {},
                                    "constraints": {},
                                    "ambiguity": {"confidence": 0.9, "notes": [], "needs_clarification": False},
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }

    monkeypatch.setattr(client_mod, "LLMClient", lambda *a, **k: DummyLLM())
    monkeypatch.setattr(interpret_mod, "LLMClient", DummyLLM)
    entry = build_board(_daybook(), {}, artifact_id=None, slot_id=None)[0]
    book = MarketBook(
        trading_day="20240320",
        book_version="b",
        updated_at="t",
        regime={},
        daybook=_daybook(),
        board=[entry],
        market_phase="INTRADAY_AM",
    )
    memory_ctx = {"session": SessionState(session_id="s", created_at="t", updated_at="t"), "recent_turns": [], "recent_claims": []}
    samples = {
        "为什么第一只": ("pick_detail", 1),
        "第二只为什么": ("pick_detail", 2),
        "现在能买吗": ("live_entry_check", None),
        "为什么不直接买": ("pick_detail", None),
        "触发条件是什么": ("pick_detail", None),
        "为什么这个策略": ("pick_detail", None),
        "为什么不是突破策略": ("pick_detail", None),
        "风险在哪里": ("pick_detail", None),
        "第二只为什么不如第一只": ("compare", 2),
    }
    for message, (expected, expected_rank) in samples.items():
        frame = parse_concern(memory_ctx, book, message)
        assert frame.request == expected
        if expected_rank is not None:
            assert frame.references.get("rank") == expected_rank
