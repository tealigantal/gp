from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import multiprocessing
import sqlite3

import pandas as pd
import pytest

from gp_assistant.application.lunch_rebalance_producer import LunchRebalanceProducer, LunchWriteBusy, _CrossProcessLock
from gp_assistant.application.conversation_service import ConversationService
from gp_assistant.application.plan_service import PlanService
from gp_assistant.application.publication_service import PublicationService
from gp_assistant.application.runtime_producer import RuntimeRecommendationProducer
from gp_assistant.application.target_resolver import resolve_plan_target
from gp_assistant.cli import _seed_serenity_target_from_current_plan, _worker_tick
from gp_assistant.contracts.catalog import CandidateDisposition, MarketPhase, RuntimeDataState
from gp_assistant.contracts.decision import CandidateDecision, TradePlan
from gp_assistant.contracts.evidence import (
    CandidateUniverseBinding,
    DecisionPolicyBinding,
    ExpertContribution,
    ProbabilityAssessment,
    ProducerIdentity,
    RankingAssessment,
    RiskAssessment,
    SerenityDecisionBinding,
    SignalAssessment,
)
from gp_assistant.contracts.market import TradingCalendarRef
from gp_assistant.contracts.ids import content_id
from gp_assistant.intraday.lunch_rebalance import LunchBatchUnavailable, collect_lunch_batch, rerank_lunch_candidates
from gp_assistant.serenity.service import POLICY_REVISION, load_active_target
from gp_assistant.store import ContractStore, ContractStoreError, PublicationConflict


TZ = timezone(timedelta(hours=8))
SESSION = date(2026, 7, 24)


def _hold_cross_process_lock(path: str, ready, release, results) -> None:
    try:
        with _CrossProcessLock(__import__("pathlib").Path(path)):
            results.put("holder_acquired")
            ready.set()
            release.wait(timeout=10)
    except Exception as exc:  # pragma: no cover - child diagnostic
        results.put(f"holder_error:{type(exc).__name__}")


def _contend_cross_process_lock(path: str, results) -> None:
    try:
        with _CrossProcessLock(__import__("pathlib").Path(path)):
            results.put("contender_acquired")
    except LunchWriteBusy:
        results.put("contender_busy")


def _candidate(symbol: str, score: float, *, finalist: bool) -> CandidateDecision:
    experts = (
        ExpertContribution(expert="serenity", contribution=0.0, weight=0.0, reason_codes=("serenity_batch_unavailable",)),
    ) if finalist else ()
    return CandidateDecision(
        symbol=symbol,
        name=symbol,
        disposition=CandidateDisposition.REJECTED,
        adaptive_score=score,
        recommendation_strength="normal",
        signal=SignalAssessment(score=0.5, label="trend", reason_codes=()),
        probability=ProbabilityAssessment(probability=0.6, confidence=0.7, effective_sample_size=30, uncertainty=0.2),
        risk=RiskAssessment(score=0.7, execution_risk=0.3, reason_codes=()),
        ranking=RankingAssessment(score=score * 0.8, rank=0, reason_codes=()),
        experts=experts,
        trade_plan=TradePlan(entry_low=10.0, entry_high=11.0, stop_price=9.0, take_profit_prices=(12.0,), action="watch", reason_codes=()),
        reason_codes=(),
    )


def _base_plan(store: ContractStore, *, serenity_active: bool = False):
    finalists = tuple(
        _candidate(f"{index + 1:06d}", 0.90 - index * 0.01, finalist=True)
        for index in range(30)
    )
    if serenity_active:
        finalists = tuple(
            item.model_copy(
                update={
                    "experts": (
                        ExpertContribution(
                            expert="serenity",
                            contribution=0.03 if index == 0 else 0.0,
                            weight=0.03,
                            reason_codes=("verified",),
                        ),
                    )
                }
            )
            for index, item in enumerate(finalists)
        )
    outsider = _candidate("600999", 0.49, finalist=False)
    target = resolve_plan_target(
        now=datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
        completed_daily_date=date(2026, 7, 23),
        calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"),
        is_open=True,
        next_open_session=date(2026, 7, 27),
        required_daily_evidence_date=date(2026, 7, 23),
    )
    plan = PlanService(store).get_or_create(
        target=target,
        universe=CandidateUniverseBinding(
            candidate_universe_id="full-market",
            content_digest="daily-digest",
            total_count=5000,
            eligible_count=199,
            complete=True,
            source="fixture",
        ),
        policy=DecisionPolicyBinding(
            revision="adaptive_kernel_v3_serenity",
            adaptive_policy_state_version="base",
            selection_policy="full_market_liquidity_ranked_top30",
            risk_profile="normal",
        ),
        producer=ProducerIdentity(name="real_daily_producer", revision="2", source_digest="daily"),
        evaluated_candidates=(*finalists, outsider),
        serenity=SerenityDecisionBinding(
            reference_id="serenity-batch" if serenity_active else None,
            policy_revision=POLICY_REVISION,
            applied_weight=0.03 if serenity_active else 0.0,
            state="active" if serenity_active else "degraded",
            reason_codes=("verified",) if serenity_active else ("serenity_batch_unavailable",),
        ),
        generated_at=datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
        selection_eligible_symbols=frozenset(item.symbol for item in finalists),
    ).plan
    publication = PublicationService(store).publish(
        plan_id=plan.plan_id,
        runtime_id=None,
        published_at=datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
    )
    return plan, publication


def _bars(*, slope: float = 0.0, missing_last: bool = False) -> pd.DataFrame:
    times = pd.date_range("2026-07-24 09:35:00", "2026-07-24 11:30:00", freq="5min")
    rows = []
    for index, trade_time in enumerate(times):
        open_price = 10.0 + slope * index
        close = open_price + slope * 0.8
        rows.append(
            {
                "trade_time": trade_time,
                "open": open_price,
                "high": max(open_price, close) + 0.02,
                "low": min(open_price, close) - 0.02,
                "close": close,
                "vol": 1000.0 + index,
                "amount": close * (1000.0 + index),
            }
        )
    frame = pd.DataFrame(rows)
    return frame.iloc[:-1].copy() if missing_last else frame


class FakeMinuteProvider:
    def __init__(self, *, incomplete_symbol: str | None = None):
        self.incomplete_symbol = incomplete_symbol
        self.calls = 0

    def get_minute_bars_5m(self, symbol, _start, _end, *, allow_fallback=True):
        assert allow_fallback is False
        self.calls += 1
        index = int(symbol)
        slope = (index - 15) * 0.001
        return _bars(slope=slope, missing_last=symbol == self.incomplete_symbol)

    def get_index_minute_bars_5m(self, symbol, _start, _end, *, allow_fallback=True):
        assert symbol == "000300"
        assert allow_fallback is False
        self.calls += 1
        return _bars(slope=0.0)


def test_complete_lunch_batch_appends_new_plan_and_preserves_database_contract(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    base_plan, base_publication = _base_plan(store)
    old_session = store.prepare_conversation(
        session_id="old-session",
        publication_id=base_publication.publication_id,
        now=datetime(2026, 7, 24, 10, 1, tzinfo=TZ),
    )
    provider = FakeMinuteProvider()

    result = LunchRebalanceProducer(store, provider=provider).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )

    assert result.state == "published"
    assert result.plan_id != base_plan.plan_id
    assert store.load_plan(base_plan.plan_id) == base_plan
    lunch_plan = store.load_plan(result.plan_id)
    current = store.current_publication()
    runtime = store.load_runtime(result.runtime_id)
    assert lunch_plan is not None and current is not None and runtime is not None
    assert current.plan_id == lunch_plan.plan_id
    assert current.runtime_id == runtime.runtime_id
    assert lunch_plan.producer.name == "lunch_5m_producer"
    assert len(lunch_plan.evaluated_candidates) == 31
    assert lunch_plan.evaluated_candidates[0].symbol != base_plan.evaluated_candidates[0].symbol
    outsider = next(item for item in lunch_plan.evaluated_candidates if item.symbol == "600999")
    assert outsider.disposition is not CandidateDisposition.SELECTED
    assert runtime.market_phase is MarketPhase.LUNCH
    assert runtime.slot_closed_at == datetime(2026, 7, 24, 11, 30, tzinfo=TZ)
    assert runtime.data_quality.state is RuntimeDataState.READY
    assert runtime.market_gate.state == "deny"
    assert len(runtime.symbol_execution_states) == 30
    assert current.decision.tradeable_now is False
    assert current.decision.reason_codes == ()
    assert store.load_runtime(current.runtime_id).market_gate.reason_codes == ("lunch_break",)
    new_session = store.prepare_conversation(
        session_id="new-session",
        publication_id=current.publication_id,
        now=datetime(2026, 7, 24, 12, 1, tzinfo=TZ),
    )
    assert old_session.publication_id == base_publication.publication_id
    assert store.session_publication("old-session") == base_publication
    assert new_session.publication_id == current.publication_id
    with pytest.raises(ContractStoreError, match="runtime_identity_mismatch"):
        store.commit_runtime(runtime.model_copy(update={"runtime_id": "runtime_forged"}))

    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("SELECT value FROM schema_metadata WHERE key='schema'").fetchone()[0] == "contract_kernel.v1"
        assert connection.execute("SELECT COUNT(*) FROM recommendation_plans").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    calls_after_publish = provider.calls
    retry = LunchRebalanceProducer(store, provider=provider).produce(
        now=datetime(2026, 7, 24, 12, 10, tzinfo=TZ)
    )
    assert retry.state == "reused"
    assert retry.plan_id == lunch_plan.plan_id
    assert provider.calls == calls_after_publish


def test_incomplete_lunch_batch_keeps_morning_publication_unchanged(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    base_plan, base_publication = _base_plan(store)

    result = LunchRebalanceProducer(
        store,
        provider=FakeMinuteProvider(incomplete_symbol="000007"),
    ).produce(now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ))

    assert result.state == "unavailable"
    assert "minute_window_incomplete" in str(result.reason)
    assert store.current_publication() == base_publication
    assert store.load_plan(base_plan.plan_id) == base_plan
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM recommendation_plans").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM runtime_observations").fetchone()[0] == 0
    finally:
        connection.close()


def test_batch_digest_is_stable_and_rejects_unclosed_or_unordered_rows():
    symbols = tuple(f"{index + 1:06d}" for index in range(30))
    first = collect_lunch_batch(
        FakeMinuteProvider(),
        reversed(symbols),
        market_session_date=SESSION,
        timezone=TZ,
    )
    second = collect_lunch_batch(
        FakeMinuteProvider(),
        symbols,
        market_session_date=SESSION,
        timezone=TZ,
    )
    assert first.content_digest == second.content_digest

    class UnorderedProvider(FakeMinuteProvider):
        def get_minute_bars_5m(self, symbol, start, end, *, allow_fallback=True):
            frame = super().get_minute_bars_5m(symbol, start, end, allow_fallback=allow_fallback)
            return frame.iloc[::-1].reset_index(drop=True) if symbol == "000010" else frame

    with pytest.raises(LunchBatchUnavailable, match="minute_window_incomplete:000010"):
        collect_lunch_batch(
            UnorderedProvider(),
            symbols,
            market_session_date=SESSION,
            timezone=TZ,
        )

    class InvalidValueProvider(FakeMinuteProvider):
        def __init__(self, mode):
            super().__init__()
            self.mode = mode

        def get_minute_bars_5m(self, symbol, start, end, *, allow_fallback=True):
            frame = super().get_minute_bars_5m(symbol, start, end, allow_fallback=allow_fallback)
            if symbol != "000011":
                return frame
            if self.mode == "null":
                frame.loc[5, "close"] = None
            elif self.mode == "duplicate":
                frame.loc[5, "trade_time"] = frame.loc[4, "trade_time"]
            else:
                frame.loc[0, "trade_time"] = pd.Timestamp("2026-07-23 09:35:00")
            return frame

    for mode, reason in (("null", "minute_values_invalid"), ("duplicate", "minute_window_incomplete"), ("mixed_date", "minute_window_incomplete")):
        with pytest.raises(LunchBatchUnavailable, match=f"{reason}:000011"):
            collect_lunch_batch(
                InvalidValueProvider(mode),
                symbols,
                market_session_date=SESSION,
                timezone=TZ,
            )


def test_worker_lunch_tick_never_runs_empty_runtime_and_afternoon_keeps_lunch_plan(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    _base_plan(store)

    class Calls:
        def __init__(self):
            self.count = 0

        def produce(self, *args, **kwargs):
            self.count += 1
            return None

    real = Calls()
    runtime = Calls()
    lunch = LunchRebalanceProducer(store, provider=FakeMinuteProvider())
    last_plan_at = 1_000.0
    monotonic_now = lambda: 1_100.0

    before_lunch = _worker_tick(
        store,
        now=datetime(2026, 7, 24, 11, 29, tzinfo=TZ),
        last_plan_at=last_plan_at,
        plan_interval_sec=1800,
        real_producer=real,
        runtime_producer=runtime,
        lunch_producer=lunch,
        monotonic_now=monotonic_now,
    )
    assert before_lunch == last_plan_at
    assert real.count == 0
    assert runtime.count == 1
    runtime.count = 0

    returned = _worker_tick(
        store,
        now=datetime(2026, 7, 24, 11, 30, tzinfo=TZ),
        last_plan_at=last_plan_at,
        plan_interval_sec=1800,
        real_producer=real,
        runtime_producer=runtime,
        lunch_producer=lunch,
        monotonic_now=monotonic_now,
    )
    assert returned == last_plan_at
    assert real.count == 0
    assert runtime.count == 0
    assert store.load_plan(store.current_publication().plan_id).producer.name == "real_daily_producer"

    _worker_tick(
        store,
        now=datetime(2026, 7, 24, 11, 32, tzinfo=TZ),
        last_plan_at=last_plan_at,
        plan_interval_sec=1800,
        real_producer=real,
        runtime_producer=runtime,
        lunch_producer=lunch,
        monotonic_now=monotonic_now,
    )
    assert store.load_plan(store.current_publication().plan_id).producer.name == "lunch_5m_producer"

    _worker_tick(
        store,
        now=datetime(2026, 7, 24, 13, 30, tzinfo=TZ),
        last_plan_at=last_plan_at,
        plan_interval_sec=1800,
        real_producer=real,
        runtime_producer=runtime,
        lunch_producer=lunch,
        monotonic_now=monotonic_now,
    )
    assert real.count == 0
    assert runtime.count == 1


def test_publication_retry_is_canonical_and_stale_pointer_write_is_rejected(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    base_plan, first = _base_plan(store)
    stale_daily = PlanService(store).get_or_create(
        target=resolve_plan_target(
            now=datetime(2026, 7, 24, 10, 10, tzinfo=TZ),
            completed_daily_date=date(2026, 7, 22),
            calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"),
            is_open=True,
            next_open_session=date(2026, 7, 27),
            required_daily_evidence_date=date(2026, 7, 22),
        ),
        universe=base_plan.candidate_universe.model_copy(update={"content_digest": "older-daily"}),
        policy=base_plan.decision_policy.model_copy(update={"adaptive_policy_state_version": "older-daily"}),
        producer=base_plan.producer.model_copy(update={"source_digest": "older-daily"}),
        evaluated_candidates=base_plan.evaluated_candidates,
        serenity=base_plan.serenity,
        generated_at=datetime(2026, 7, 24, 10, 10, tzinfo=TZ),
        selection_eligible_symbols=frozenset(
            item.symbol for item in base_plan.evaluated_candidates if any(expert.expert == "serenity" for expert in item.experts)
        ),
    ).plan
    with pytest.raises(ValueError, match="stale_publication_write"):
        PublicationService(store).publish(
            plan_id=stale_daily.plan_id,
            runtime_id=None,
            published_at=datetime(2026, 7, 24, 10, 10, tzinfo=TZ),
        )
    retry = PublicationService(store).publish(
        plan_id=first.plan_id,
        runtime_id=None,
        published_at=datetime(2026, 7, 24, 10, 5, tzinfo=TZ),
    )
    assert retry == first
    assert retry.published_at == datetime(2026, 7, 24, 10, 0, tzinfo=TZ)

    lunch = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )
    assert lunch.state == "published"
    with pytest.raises(PublicationConflict, match="stale_publication_write"):
        store.commit_publication(first, expected_current_publication_id=first.publication_id)
    with pytest.raises(ValueError, match="stale_publication_write"):
        PublicationService(store).publish(
            plan_id=first.plan_id,
            runtime_id=None,
            published_at=datetime(2026, 7, 24, 12, 1, tzinfo=TZ),
        )


def test_llm_receives_product_level_lunch_principle_without_engine_interfaces(tmp_path):
    captured = {}

    class Narrator:
        def available(self):
            return True, "ok"

        def chat(self, messages, **_kwargs):
            captured["messages"] = messages
            return {"choices": [{"message": {"content": "午盘已按上午闭合数据重排，但午休不能交易。"}}]}

    store = ContractStore(tmp_path / "contract.sqlite")
    _base_plan(store, serenity_active=True)
    result = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )
    assert result.state == "published"

    ConversationService(store, narrator=Narrator()).reply(
        session_id="lunch-chat",
        client_turn_id="turn-1",
        user_message="午盘为什么这样排序？",
    )

    system_prompt = captured["messages"][0]["content"]
    user_payload = captured["messages"][1]["content"]
    assert "45% 是股票上午涨跌相对沪深300的强弱" in system_prompt
    assert "午休市场门禁始终禁止交易" in system_prompt
    assert "午盘最终排序分" in user_payload
    assert "相对早盘综合分的实际改变量" in user_payload
    assert "batch_digest" not in user_payload
    assert "lunch_5m_producer" not in user_payload
    assert "source_digest" not in user_payload
    assert "publication_id" not in user_payload
    assert "plan_id" not in user_payload
    assert "runtime_id" not in user_payload
    assert "reason_codes" not in user_payload


def test_lunch_keeps_existing_public_http_shapes(tmp_path, monkeypatch):
    db_path = tmp_path / "contract.sqlite"
    monkeypatch.setenv("GP_CONTRACT_DB", str(db_path))
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.sqlite"))
    store = ContractStore(db_path)
    _base_plan(store)
    result = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )
    assert result.state == "published"

    from fastapi.testclient import TestClient
    from gp_assistant.gateway.app import app

    with TestClient(app) as client:
        recommendation = client.get("/api/recommendation/current")
        lunch = client.get("/api/lunch/current")
        health = client.get("/api/health")

    assert recommendation.status_code == 200
    assert set(recommendation.json()) == {
        "publication_id",
        "plan_id",
        "runtime_id",
        "published_at",
        "decision",
        "candidates",
        "lineage",
    }
    assert lunch.status_code == 200
    assert set(lunch.json()) == {
        "market_session_date",
        "plan_id",
        "runtime_id",
        "publication_id",
        "morning_slot_closed_at",
        "morning_session_state",
        "tradeable_now",
        "reason_codes",
    }
    assert health.status_code == 200
    assert set(health.json()) == {
        "current_publication_id",
        "plan_id",
        "runtime_id",
        "market_session_date",
        "daily_evidence_date",
        "slot_closed_at",
        "market_phase",
        "daily_data_state",
        "runtime_data_state",
        "publication_state",
        "tradeability_state",
        "serenity",
    }
    recommendation_payload = recommendation.json()
    lunch_payload = lunch.json()
    health_payload = health.json()
    assert isinstance(recommendation_payload["publication_id"], str)
    assert isinstance(recommendation_payload["candidates"], list)
    assert isinstance(recommendation_payload["decision"], dict)
    assert isinstance(lunch_payload["morning_slot_closed_at"], str)
    assert lunch_payload["morning_session_state"] == "lunch"
    assert lunch_payload["tradeable_now"] is False
    assert isinstance(lunch_payload["reason_codes"], list)
    assert isinstance(health_payload["serenity"], dict)


def test_active_serenity_three_percent_survives_lunch_rerank():
    symbols = tuple(f"{index + 1:06d}" for index in range(30))
    batch = collect_lunch_batch(
        FakeMinuteProvider(),
        symbols,
        market_session_date=SESSION,
        timezone=TZ,
    )
    candidates = tuple(_candidate(symbol, 0.6, finalist=True) for symbol in symbols)
    first = candidates[0].model_copy(
        update={
            "experts": (
                ExpertContribution(expert="serenity", contribution=0.03, weight=0.03, reason_codes=("verified",)),
            )
        }
    )
    reranked = rerank_lunch_candidates(
        (first, *candidates[1:]),
        eligible_symbols=frozenset(symbols),
        batch=batch,
    )
    expected = min(1.0, batch.signals[first.symbol].score + 0.03)
    assert reranked[0].adaptive_score == pytest.approx(expected)
    assert next(expert for expert in reranked[0].experts if expert.expert == "serenity").weight == 0.03


def test_active_serenity_three_percent_survives_lunch_production_and_persistence(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    _base_plan(store, serenity_active=True)
    result = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )

    plan = store.load_plan(result.plan_id)
    runtime = store.load_runtime(result.runtime_id)
    signal_by_symbol = {item.symbol: item.intraday_score for item in runtime.symbol_execution_states}
    first = next(item for item in plan.evaluated_candidates if item.symbol == "000001")
    serenity = next(expert for expert in first.experts if expert.expert == "serenity")

    assert plan.serenity.applied_weight == 0.03
    assert serenity.weight == 0.03
    assert serenity.contribution == 0.03
    assert first.adaptive_score == pytest.approx(min(1.0, signal_by_symbol[first.symbol] + 0.03))
    assert all(
        next(expert for expert in item.experts if expert.expert == "serenity").weight == 0.03
        for item in plan.evaluated_candidates[:30]
    )


def test_manual_lunch_runtime_refresh_preserves_complete_lunch_observation(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    _base_plan(store)
    result = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )
    before = store.current_publication()
    runtime = RuntimeRecommendationProducer(store, spot_loader=lambda: pytest.fail("spot must not load during lunch")).produce(
        now=datetime(2026, 7, 24, 12, 5, tzinfo=TZ)
    )
    assert runtime.runtime_id == result.runtime_id
    assert len(runtime.symbol_execution_states) == 30
    assert store.current_publication() == before


def test_worker_restart_seeds_serenity_from_original_frozen_scope_and_base_scores(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_SERENITY_CURRENT_DB", str(tmp_path / "serenity.sqlite"))
    store = ContractStore(tmp_path / "contract.sqlite")
    base_plan, _publication = _base_plan(store)
    result = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )
    assert result.state == "published"

    _seed_serenity_target_from_current_plan(store, datetime(2026, 7, 24, 12, 5, tzinfo=TZ))
    target = load_active_target()
    expected = {
        item.symbol: item.adaptive_score
        for item in base_plan.evaluated_candidates
        if any(expert.expert == "serenity" for expert in item.experts)
    }
    assert target is not None
    assert set(target.symbols) == set(expected)
    assert target.base_scores == pytest.approx(expected)


def test_base_change_during_collection_cannot_be_overwritten(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    base_plan, _base_publication = _base_plan(store)
    provider = FakeMinuteProvider()

    def replacing_loader(provider_arg, symbols, **kwargs):
        replacement = PlanService(store).get_or_create(
            target=resolve_plan_target(
                now=datetime(2026, 7, 24, 11, 40, tzinfo=TZ),
                completed_daily_date=date(2026, 7, 23),
                calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"),
                is_open=True,
                next_open_session=date(2026, 7, 27),
                required_daily_evidence_date=date(2026, 7, 23),
            ),
            universe=base_plan.candidate_universe,
            policy=base_plan.decision_policy.model_copy(update={"adaptive_policy_state_version": "base-b"}),
            producer=base_plan.producer.model_copy(update={"source_digest": "daily-b"}),
            evaluated_candidates=base_plan.evaluated_candidates,
            serenity=base_plan.serenity,
            generated_at=datetime(2026, 7, 24, 11, 40, tzinfo=TZ),
            selection_eligible_symbols=frozenset(
                item.symbol for item in base_plan.evaluated_candidates if any(expert.expert == "serenity" for expert in item.experts)
            ),
        ).plan
        PublicationService(store).publish(
            plan_id=replacement.plan_id,
            runtime_id=None,
            published_at=datetime(2026, 7, 24, 11, 40, tzinfo=TZ),
        )
        return collect_lunch_batch(provider_arg, symbols, **kwargs)

    result = LunchRebalanceProducer(store, provider=provider, batch_loader=replacing_loader).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )
    current = store.current_publication()
    assert result.state == "unavailable"
    assert result.reason == "stale_base_publication"
    assert store.load_plan(current.plan_id).producer.source_digest == "daily-b"


def test_failure_after_plan_and_runtime_append_keeps_morning_current(tmp_path, monkeypatch):
    store = ContractStore(tmp_path / "contract.sqlite")
    _base_plan(store)
    morning = store.current_publication()

    def fail_publish(*_args, **_kwargs):
        raise PublicationConflict("injected_publish_failure")

    monkeypatch.setattr(PublicationService, "publish", fail_publish)
    result = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )

    assert result.state == "unavailable"
    assert store.current_publication() == morning
    connection = sqlite3.connect(store.path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM recommendation_plans").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM runtime_observations").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_cross_process_write_lock_and_store_lineage_guard(tmp_path):
    lock_path = tmp_path / ".lunch.lock"
    with _CrossProcessLock(lock_path):
        with pytest.raises(LunchWriteBusy):
            with _CrossProcessLock(lock_path):
                pass

    store = ContractStore(tmp_path / "contract.sqlite")
    stored_plan, publication = _base_plan(store)
    with pytest.raises(ContractStoreError, match="plan_identity_mismatch"):
        store.commit_plan(stored_plan.model_copy(update={"plan_id": "plan_forged"}))
    forged = publication.model_copy(update={"candidates": ()})
    with pytest.raises(ContractStoreError, match="publication_lineage_mismatch"):
        store.commit_publication(forged, expected_current_publication_id=publication.publication_id)

    forged_decision = publication.decision.model_copy(update={"tradeable_now": True})
    identity = json.dumps(
        {
            "plan_id": publication.plan_id,
            "runtime_id": publication.runtime_id,
            "decision": forged_decision.model_dump(mode="json"),
            "lineage": publication.lineage.model_dump(mode="json"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    forged_tradeable = publication.model_copy(
        update={
            "publication_id": content_id("publication", identity),
            "decision": forged_decision,
        }
    )
    with pytest.raises(ContractStoreError, match="publication_decision_mismatch"):
        store.commit_publication(forged_tradeable, expected_current_publication_id=publication.publication_id)


def test_write_lock_is_exclusive_across_spawned_processes(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    results = context.Queue()
    lock_path = str(tmp_path / ".multiprocess-lunch.lock")
    holder = context.Process(target=_hold_cross_process_lock, args=(lock_path, ready, release, results))
    contender = context.Process(target=_contend_cross_process_lock, args=(lock_path, results))
    holder.start()
    assert ready.wait(timeout=10)
    contender.start()
    contender.join(timeout=10)
    release.set()
    holder.join(timeout=10)
    assert holder.exitcode == 0
    assert contender.exitcode == 0
    assert {results.get(timeout=2), results.get(timeout=2)} == {"holder_acquired", "contender_busy"}


@pytest.mark.parametrize(
    "leaked_content",
    (
        "内部 plan_id 是 abc。",
        "内部 reason_codes 为 lunch_break。",
        "请调用 /api/lunch/current。",
        "数据保存在 SQLite 表中。",
        "```json\n{\"score\": 1}\n```",
    ),
)
def test_llm_internal_identifier_output_is_rejected_before_persistence(tmp_path, leaked_content):
    class LeakingNarrator:
        def available(self):
            return True, "ok"

        def chat(self, *_args, **_kwargs):
            return {"choices": [{"message": {"content": leaked_content}}]}

    store = ContractStore(tmp_path / "contract.sqlite")
    _base_plan(store)
    with pytest.raises(ValueError, match="narration_unsafe_internal_detail"):
        ConversationService(store, narrator=LeakingNarrator()).reply(
            session_id="unsafe",
            client_turn_id="turn-1",
            user_message="解释推荐",
        )
    assert store.existing_reply(session_id="unsafe", client_turn_id="turn-1") is None


def test_afternoon_runtime_keeps_all_top30_lunch_scores_explainable(tmp_path):
    captured = {}

    class Narrator:
        def available(self):
            return True, "ok"

        def chat(self, messages, **_kwargs):
            captured["payload"] = json.loads(messages[1]["content"])
            return {"choices": [{"message": {"content": "午盘排序依据仍可解释。"}}]}

    store = ContractStore(tmp_path / "contract.sqlite")
    _base_plan(store, serenity_active=True)
    result = LunchRebalanceProducer(store, provider=FakeMinuteProvider()).produce(
        now=datetime(2026, 7, 24, 12, 0, tzinfo=TZ)
    )
    lunch_plan = store.load_plan(result.plan_id)
    expected_scores = {item.symbol: item.adaptive_score for item in lunch_plan.evaluated_candidates[:30]}
    selected = [item.symbol for item in lunch_plan.evaluated_candidates if item.disposition is CandidateDisposition.SELECTED]
    spot = pd.DataFrame({"code": selected, "price": [10.2] * len(selected), "pct_chg": [1.0] * len(selected)})
    RuntimeRecommendationProducer(store, spot_loader=lambda: spot).produce(
        now=datetime(2026, 7, 24, 13, 5, tzinfo=TZ)
    )

    ConversationService(store, narrator=Narrator()).reply(
        session_id="afternoon",
        client_turn_id="turn-1",
        user_message="解释午盘全部候选",
    )
    effects = [
        (item["股票代码"], item["午盘五分钟实际影响"])
        for item in captured["payload"]["当前事实"]["候选列表"]
        if item["午盘五分钟实际影响"] is not None
    ]
    assert len(effects) == 30
    assert all(effect["午盘最终排序分"] == round(expected_scores[symbol], 6) for symbol, effect in effects)
