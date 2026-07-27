from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from gp_assistant.application.plan_service import PlanService
from gp_assistant.application.publication_service import PublicationService
from gp_assistant.application.runtime_service import RuntimeService
from gp_assistant.application.target_resolver import resolve_plan_target
from gp_assistant.application.runtime_producer import RuntimeRecommendationProducer
from gp_assistant.application.conversation_service import ConversationService
from gp_assistant.contracts.catalog import CandidateDisposition, MarketPhase, RuntimeDataState
from gp_assistant.contracts.decision import CandidateDecision, TradePlan
from gp_assistant.contracts.evidence import CandidateUniverseBinding, DecisionPolicyBinding, ProbabilityAssessment, ProducerIdentity, RankingAssessment, RiskAssessment, SerenityDecisionBinding, SignalAssessment
from gp_assistant.contracts.market import TradingCalendarRef
from gp_assistant.contracts.runtime import MarketGate, RuntimeDataQuality, RuntimeObservation, SymbolExecutionState
from gp_assistant.store import ContractStore


TZ = timezone(timedelta(hours=8))


def candidate(symbol: str = "000001") -> CandidateDecision:
    return CandidateDecision(symbol=symbol, name="测试", disposition=CandidateDisposition.REJECTED, adaptive_score=0.7, recommendation_strength="normal", signal=SignalAssessment(score=0.7, label="trend", reason_codes=()), probability=ProbabilityAssessment(probability=0.6, confidence=0.7, effective_sample_size=30, uncertainty=0.2), risk=RiskAssessment(score=0.6, execution_risk=0.2, reason_codes=()), ranking=RankingAssessment(score=0.7, rank=99, reason_codes=()), experts=(), trade_plan=TradePlan(entry_low=10, entry_high=11, stop_price=9, take_profit_prices=(12,), action="watch", reason_codes=()), reason_codes=())


def plan(store: ContractStore):
    target = resolve_plan_target(now=datetime(2026, 7, 22, 16, 0, tzinfo=TZ), completed_daily_date=date(2026, 7, 22), calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"), is_open=True, next_open_session=date(2026, 7, 23), required_daily_evidence_date=date(2026, 7, 22))
    return PlanService(store).get_or_create(target=target, universe=CandidateUniverseBinding(candidate_universe_id="universe_a", content_digest="digest", total_count=3, eligible_count=3, complete=True, source="fixture"), policy=DecisionPolicyBinding(revision="policy", adaptive_policy_state_version="1", selection_policy="adaptive", risk_profile="normal"), producer=ProducerIdentity(name="fixture", revision="1", source_digest="source"), evaluated_candidates=(candidate(),), serenity=SerenityDecisionBinding(reference_id=None, policy_revision="1", applied_weight=0.0, state="shadow", reason_codes=("causal_gate_not_ready",)), generated_at=datetime(2026, 7, 22, 16, 1, tzinfo=TZ)).plan


def test_target_lifecycle_and_plan_reuse(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    first = plan(store)
    second = plan(store)
    assert first.plan_id == second.plan_id
    lunch = resolve_plan_target(now=datetime(2026, 7, 23, 12, 46, tzinfo=TZ), completed_daily_date=date(2026, 7, 22), calendar=TradingCalendarRef(calendar_id="cn", revision="1", source="fixture"), is_open=True, next_open_session=date(2026, 7, 24), required_daily_evidence_date=date(2026, 7, 22))
    assert lunch.market_session_date == date(2026, 7, 23)
    assert lunch.daily_evidence_date == date(2026, 7, 22)


def test_runtime_cannot_change_plan_and_publication_is_linked(tmp_path):
    store = ContractStore(tmp_path / "contract.sqlite")
    selected_plan = plan(store)
    observation = RuntimeObservation(runtime_id="ignored", plan_id=selected_plan.plan_id, market=selected_plan.market, market_session_date=selected_plan.market_session_date, observed_at=datetime(2026, 7, 23, 12, 46, tzinfo=TZ), slot_closed_at=datetime(2026, 7, 23, 11, 30, tzinfo=TZ), market_phase=MarketPhase.LUNCH, data_quality=RuntimeDataQuality(state=RuntimeDataState.READY, source="fixture", reason_codes=()), market_gate=MarketGate(state="allow", score=0.8, reason_codes=()), symbol_execution_states=(SymbolExecutionState(symbol="000001", state="ready", vwap=10.5, intraday_score=0.7, reason_codes=()),), producer_name="fixture", producer_revision="1")
    runtime = RuntimeService(store).observe(observation)
    publication = PublicationService(store).publish(plan_id=selected_plan.plan_id, runtime_id=runtime.runtime_id, published_at=datetime(2026, 7, 23, 12, 46, tzinfo=TZ))
    assert publication.plan_id == selected_plan.plan_id
    assert publication.runtime_id == runtime.runtime_id
    assert publication.decision.tradeable_now
    invalid = observation.model_copy(update={"symbol_execution_states": (SymbolExecutionState(symbol="600000", state="ready", vwap=1, intraday_score=1, reason_codes=()),)})
    with pytest.raises(ValueError, match="runtime_symbol_outside_plan"):
        RuntimeService(store).observe(invalid)


def test_runtime_producer_and_conversation_are_bound_and_idempotent(tmp_path):
    import pandas as pd

    class Narrator:
        def available(self):
            return True, "ok"

        def chat(self, *_args, **_kwargs):
            return {"choices": [{"message": {"content": "回答严格绑定当前发布。"}}]}

    store = ContractStore(tmp_path / "contract.sqlite")
    selected_plan = plan(store)
    PublicationService(store).publish(plan_id=selected_plan.plan_id, runtime_id=None, published_at=datetime(2026, 7, 23, 9, 30, tzinfo=TZ))
    runtime = RuntimeRecommendationProducer(
        store,
        spot_loader=lambda: pd.DataFrame({"code": ["000001"], "price": [10.2], "pct_chg": [1.0]}),
    ).produce(now=datetime(2026, 7, 23, 10, 1, tzinfo=TZ))
    PublicationService(store).publish(plan_id=selected_plan.plan_id, runtime_id=runtime.runtime_id, published_at=datetime(2026, 7, 23, 10, 1, tzinfo=TZ))
    publication = store.current_publication()
    assert runtime.data_quality.state is RuntimeDataState.READY
    assert publication is not None and publication.decision.tradeable_now
    service = ConversationService(store, narrator=Narrator())
    first = service.reply(session_id=None, client_turn_id="turn-1", user_message="说明当前推荐")
    retry = service.reply(session_id=first["session_id"], client_turn_id="turn-1", user_message="说明当前推荐")
    assert retry["reply"] == first["reply"]
    assert retry["publication_id"] == publication.publication_id


def test_canonical_conversation_reads_are_available_to_the_workspace(tmp_path, monkeypatch):
    class Narrator:
        def available(self):
            return True, "ok"

        def chat(self, *_args, **_kwargs):
            return {"choices": [{"message": {"content": "已绑定发布的回复。"}}]}

    db_path = tmp_path / "contract.sqlite"
    monkeypatch.setenv("GP_CONTRACT_DB", str(db_path))
    store = ContractStore(db_path)
    selected_plan = plan(store)
    PublicationService(store).publish(plan_id=selected_plan.plan_id, runtime_id=None, published_at=datetime(2026, 7, 23, 9, 30, tzinfo=TZ))
    exchange = ConversationService(store, narrator=Narrator()).reply(session_id="session_workspace", client_turn_id="turn-workspace", user_message="解释计划")

    from fastapi.testclient import TestClient
    from gp_assistant.gateway.app import app

    with TestClient(app) as client:
        sessions = client.get("/api/conversations")
        detail = client.get("/api/conversations/session_workspace")

    assert sessions.status_code == 200
    assert sessions.json()[0]["session_id"] == "session_workspace"
    assert detail.status_code == 200
    assert [item["content"] for item in detail.json()["turns"]] == ["解释计划", exchange["reply"]]


def test_delete_conversation_removes_only_the_session_and_cascaded_turns(tmp_path, monkeypatch):
    class Narrator:
        def available(self):
            return True, "ok"

        def chat(self, *_args, **_kwargs):
            return {"choices": [{"message": {"content": "可删除的回复。"}}]}

    db_path = tmp_path / "contract.sqlite"
    monkeypatch.setenv("GP_CONTRACT_DB", str(db_path))
    store = ContractStore(db_path)
    selected_plan = plan(store)
    publication = PublicationService(store).publish(plan_id=selected_plan.plan_id, runtime_id=None, published_at=datetime(2026, 7, 23, 9, 30, tzinfo=TZ))
    service = ConversationService(store, narrator=Narrator())
    service.reply(session_id="session_delete", client_turn_id="turn-delete", user_message="删除这条")
    service.reply(session_id="session_keep", client_turn_id="turn-keep", user_message="保留这条")

    from fastapi.testclient import TestClient
    from gp_assistant.gateway.app import app

    with TestClient(app) as client:
        deleted = client.delete("/api/conversations/session_delete")
        missing = client.get("/api/conversations/session_delete")
        repeated = client.delete("/api/conversations/session_delete")
        kept = client.get("/api/conversations/session_keep")
        resurrection = client.post("/api/chat", json={"session_id": "session_delete", "client_turn_id": "turn-late", "message": "迟到请求"})

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert missing.status_code == 404
    assert repeated.status_code == 404
    assert kept.status_code == 200
    assert [turn["content"] for turn in kept.json()["turns"]] == ["保留这条", "可删除的回复。"]
    assert resurrection.status_code == 409
    assert resurrection.json()["detail"] == "conversation_deleted"
    assert store.existing_reply(session_id="session_delete", client_turn_id="turn-delete") is None
    assert store.existing_reply(session_id="session_keep", client_turn_id="turn-keep") == "可删除的回复。"
    assert store.current_publication() == publication
    assert store.load_plan(selected_plan.plan_id) == selected_plan
