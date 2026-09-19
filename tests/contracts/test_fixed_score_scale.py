"""Fixed evaluation scale acceptance; v6 exists only as a test reference."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
from types import SimpleNamespace

import pytest

from gp_assistant.application import real_producer as producer
from gp_assistant.application.conversation_service import ConversationService
from gp_assistant.application.lunch_rebalance_producer import LunchRebalanceProducer
from gp_assistant.core.paths import configs_dir
from gp_assistant.decision_engine.adaptive import AdaptiveDecisionEngine
from gp_assistant.decision_engine.scoring import (
    REVISION, _policy_digest, load_scoring_policy, score_candidate,
)
from gp_assistant.intraday.lunch_rebalance import collect_lunch_batch, observe_lunch_candidates
from gp_assistant.store import ContractStore
from tests.contracts.test_lunch_rebalance import FakeMinuteProvider, SESSION, TZ, _base_plan
from tests.contracts.test_serenity_fixed_weight import _candidate


def v6_score(*, gain, loss, support, a0, n0=20.):
    """Exact pre-change valid-input calculation, never a production fallback."""
    scale = max(gain, loss, a0)
    weight_scale = max(support, n0)
    g, l, a = gain / scale, loss / scale, a0 / scale
    n, prior = support / weight_scale, n0 / weight_scale
    return (n * g + 0.5 * prior * a) / (n * (g + l) + prior * a)


@pytest.mark.parametrize("gain,old_percent,new_percent", [
    (.006,40.,11.428571428571), (.008,45.,20.), (.010,50.,50.),
    (.012,55.,80.), (.014,60.,88.571428571429),
])
def test_fixed_scale_anchors_through_real_function(gain,old_percent,new_percent):
    values = dict(gain=gain,loss=.02-gain,support=20.,a0=.02,n0=20.)
    assert v6_score(**values)*100 == pytest.approx(old_percent)
    assert score_candidate(**values)["score"]*100 == pytest.approx(new_percent)


def test_ranking_matches_v6_including_symbol_ties_and_top30_scope():
    rng = random.Random(190926)
    inputs = [dict(gain=rng.uniform(0,.15),loss=rng.uniform(0,.15),
                   support=rng.uniform(.01,100),a0=.03997941946323374,n0=20.) for _ in range(200)]
    # Exact ties use the same input, while support and amplitudes vary elsewhere.
    inputs.extend([deepcopy(inputs[0]), deepcopy(inputs[0])])
    old = tuple(_candidate(f"{len(inputs)-i:06d}",v6_score(**row)) for i,row in enumerate(inputs))
    new = tuple(_candidate(c.symbol,score_candidate(**row)["score"]) for c,row in zip(old,inputs))
    old_order = sorted(old,key=lambda c:(-c.adaptive_score,c.symbol))
    new_order = sorted(new,key=lambda c:(-c.adaptive_score,c.symbol))
    assert [c.symbol for c in new_order] == [c.symbol for c in old_order]
    eligible = frozenset(c.symbol for c in new_order[:30])
    for values in (old,new):
        chosen = AdaptiveDecisionEngine().select(values,selection_eligible_symbols=eligible)
        assert [c.symbol for c in chosen if c.disposition.value=="selected"] == [c.symbol for c in new_order[:3]]


@pytest.mark.parametrize("gain,loss", [(0.,0.),(.01,.01),(.03,.005),(.005,.03)])
def test_return_shape_and_risk_facts_are_unchanged(gain,loss):
    result = score_candidate(gain=gain,loss=loss,support=20,a0=.04,n0=20)
    assert set(result) == {"score","expected_net_return","reason_codes"}
    assert result["expected_net_return"] == gain-loss
    assert result["reason_codes"] == (() if gain>loss else ("nonpositive_net_edge",))


@pytest.mark.parametrize("gain,loss,support,a0,n0", [
    (1e308,0.,1e308,1e-308,1.), (0.,1e308,1e308,1e-308,1.),
    (1e-300,0.,1e-300,1e-300,1e-300), (0.,0.,1e308,.04,20.),
])
def test_scaled_extreme_inputs_remain_finite(gain,loss,support,a0,n0):
    result = score_candidate(gain=gain,loss=loss,support=support,a0=a0,n0=n0)
    assert math.isfinite(result["score"]) and 0 <= result["score"] <= 1


def test_policy_identity_changes_without_refreezing_reference():
    payload = json.loads((configs_dir()/"daily_scoring.json").read_text(encoding="utf-8"))
    assert payload["revision"] == REVISION == "daily_score_v7_fixed_scale_gain_loss"
    assert producer.DAILY_PRODUCER_REVISION == "6"
    assert payload["a0"] == .03997941946323374
    assert payload["n0"] == 20. and payload["round_trip_cost"] == .003
    assert payload["reference"]["frozen_at"] == "2026-09-18T15:40:07+08:00"
    assert payload["reference"]["source_digest"] == "9f2be0fbb44f2d092dd1882ef4f599d6f44e7f3f307693d94fc3b8dcd39c0ef6"
    old = {**payload,"revision":"daily_score_v6_smoothed_gain_loss"}
    loaded = load_scoring_policy(evidence_day="2026-09-18",known_at=datetime(2026,9,19,tzinfo=timezone.utc))
    assert loaded.digest != _policy_digest(old)


def test_new_scale_serenity_once_lunch_preserves_and_final_order_can_change():
    inputs = [dict(gain=.012,loss=.008,support=20.,a0=.02,n0=20.),
              dict(gain=.0132,loss=.0068,support=20.,a0=.02,n0=20.)]
    inputs.extend([dict(gain=.01,loss=.01,support=20.,a0=.02,n0=20.) for _ in range(28)])
    def candidates(scores):
        return tuple(_candidate(f"{i+1:06d}",s).model_copy(update={
            "ranking":_candidate(f"{i+1:06d}",s).ranking.model_copy(update={"core_score":s}),
        }) for i,s in enumerate(scores))
    old = candidates([v6_score(**v) for v in inputs])
    new = candidates([score_candidate(**v)["score"] for v in inputs])
    decision = SimpleNamespace(applied_weight=.03,alphas={"000001":1.,"000002":0.},reasons={},reason_codes=())
    old_final = producer.RealRecommendationProducer._apply_serenity(old,decision)
    new_final = producer.RealRecommendationProducer._apply_serenity(new,decision)
    assert producer.RealRecommendationProducer._apply_serenity(new_final,decision) == new_final
    engine = AdaptiveDecisionEngine()
    # Same base order, but fixed +/-3 points on the new scale can change final order.
    assert engine.select(old)[0].symbol == engine.select(new)[0].symbol == "000002"
    assert engine.select(old_final)[0].symbol == "000001"
    assert engine.select(new_final)[0].symbol == "000002"
    batch = collect_lunch_batch(FakeMinuteProvider(),tuple(c.symbol for c in new),market_session_date=SESSION,timezone=TZ)
    observed = observe_lunch_candidates(new_final,eligible_symbols=frozenset(c.symbol for c in new),batch=batch)
    for base,final,lunch in zip(new,new_final,observed):
        assert final.ranking.score == final.adaptive_score
        assert final.ranking.core_score == base.adaptive_score
        assert final.probability == base.probability == lunch.probability
        assert lunch.ranking == final.ranking and lunch.adaptive_score == final.adaptive_score
        assert next(e for e in lunch.experts if e.expert=="serenity") == final.experts[0]
        assert next(e for e in lunch.experts if e.expert=="intraday_5m").contribution == 0.


def test_v6_lunch_identity_is_rejected_before_reuse_or_collection():
    old = SimpleNamespace(market_session_date=SESSION,plan_id="old_lunch",
                          producer=SimpleNamespace(name="lunch_5m_producer",revision="3"))
    publication = SimpleNamespace(plan_id=old.plan_id,publication_id="old_publication")
    store = SimpleNamespace(current_publication=lambda:publication,load_plan=lambda _:old)
    result = LunchRebalanceProducer(store,batch_loader=lambda *a,**kw:pytest.fail("must not collect")).produce(
        now=datetime(2026,7,24,12,tzinfo=TZ))
    assert result.reason == "obsolete_lunch_policy"


@pytest.mark.parametrize("revision,producer_revision,recorded_score", [
    ("daily_score_v6_smoothed_gain_loss","5",.55),
    ("daily_score_v7_fixed_scale_gain_loss","6",.80),
])
def test_narration_quotes_each_policy_record_without_transforming(tmp_path,monkeypatch,revision,producer_revision,recorded_score):
    from gp_assistant.application.plan_service import PlanService
    from gp_assistant.application.publication_service import PublicationService
    from gp_assistant.application.target_resolver import resolve_plan_target
    from gp_assistant.contracts.market import TradingCalendarRef
    from gp_assistant.decision_engine import scoring

    store = ContractStore(tmp_path/"contracts.sqlite")
    template, _ = _base_plan(store)
    rows = tuple(c.model_copy(update={
        "adaptive_score":recorded_score,
        "ranking":c.ranking.model_copy(update={"score":recorded_score,"core_score":recorded_score,
            "policy_revision":revision,"gain":.012,"loss":.008,"support":20.,"a0":.02,"n0":20.}),
    }) for c in template.evaluated_candidates)
    target = resolve_plan_target(now=template.generated_at,completed_daily_date=template.daily_evidence_date,
        calendar=TradingCalendarRef(calendar_id="cn",revision="1",source="fixture"),is_open=True,
        next_open_session=template.market_session_date,required_daily_evidence_date=template.daily_evidence_date)
    recorded = PlanService(store).get_or_create(target=target,universe=template.candidate_universe,
        policy=template.decision_policy.model_copy(update={"revision":revision,"adaptive_policy_state_version":"narration"}),
        producer=template.producer.model_copy(update={"revision":producer_revision}),
        evaluated_candidates=rows,serenity=template.serenity,generated_at=template.generated_at).plan
    PublicationService(store).publish(plan_id=recorded.plan_id,runtime_id=None,published_at=recorded.generated_at)
    assert all(c.ranking.core_score is not None and c.ranking.policy_revision == revision for c in recorded.evaluated_candidates)
    def forbidden_recalculation(**kwargs):
        pytest.fail("historical reading and narration must not calculate a new score")
    monkeypatch.setattr(scoring,"score_candidate",forbidden_recalculation)
    monkeypatch.setattr(producer,"score_candidate",forbidden_recalculation)
    captured = {}
    class Narrator:
        def available(self): return True,"ok"
        def chat(self,messages,**kwargs):
            captured["messages"] = messages
            return {"choices":[{"message":{"content":"仅供优先观察。"}}]}
    before = store.current_publication()
    ConversationService(store,narrator=Narrator()).reply(session_id="fixed",client_turn_id="first",user_message="解释评分")
    payload = json.loads(captured["messages"][1]["content"])
    facts = payload["当前事实"]["候选列表"]
    assert [c["综合分"] for c in facts] == [round(c.adaptive_score*100,4) for c in before.candidates]
    assert all(c["综合分"] == pytest.approx(recorded_score*100,abs=1e-12,rel=0) for c in facts)
    assert all(c["评分口径"] == "总分为本计划生成时记录的相对评价，不是上涨概率或收益保证；不同评分政策的分数不能直接跨版本比较。" for c in facts)
    assert "不得再次换算" in captured["messages"][0]["content"]
    assert "不同评分政策的分数不能直接跨版本比较" in captured["messages"][0]["content"]
    assert store.load_plan(recorded.plan_id) == recorded
    assert store.current_publication() == before


@pytest.mark.parametrize("plan_index", [0,1])
def test_saved_complete_plan_inputs_match_v6_order_and_fixed_scale(plan_index):
    # Two versions of the same evidence day, not independent backtest samples.
    path = Path(__file__).resolve().parents[2]/"reports/fixed-score-scale-20260919/readonly-comparison.json"
    original = path.read_bytes()
    plan = json.loads(original)["plans"][plan_index]
    assert len(plan["rows"]) == 198
    old, new = [], []
    for row in plan["rows"]:
        values = {k:row[k] for k in ("gain","loss","support","a0","n0")}
        old_score = v6_score(**values)
        result = score_candidate(**values)
        assert old_score == pytest.approx(row["old_core"],abs=1e-12,rel=0)
        assert result["score"] == pytest.approx(row["new_core"],abs=1e-12,rel=0)
        assert result["expected_net_return"] == row["gain"]-row["loss"]
        old.append(_candidate(row["symbol"],old_score))
        new.append(_candidate(row["symbol"],result["score"]))
    old_order = sorted(old,key=lambda c:(-c.adaptive_score,c.symbol))
    new_order = sorted(new,key=lambda c:(-c.adaptive_score,c.symbol))
    assert [c.symbol for c in new_order] == [c.symbol for c in old_order]
    assert [c.symbol for c in new_order[:30]] == [c.symbol for c in old_order[:30]]
    zero = SimpleNamespace(applied_weight=0.,alphas={},reasons={},reason_codes=())
    final = producer.RealRecommendationProducer._apply_serenity(tuple(new),zero)
    selected = AdaptiveDecisionEngine().select(final,selection_eligible_symbols=frozenset(c.symbol for c in new_order[:30]))
    assert [c.symbol for c in selected if c.disposition.value=="selected"] == [c.symbol for c in old_order[:3]]
    assert [c.adaptive_score*100 for c in new_order[:3]] == pytest.approx([81.548689,80.893365,80.462265],abs=1e-6,rel=0)
    assert min(c.adaptive_score*100 for c in new) == pytest.approx(6.49,abs=.005,rel=0)
    assert max(c.adaptive_score*100 for c in new) == pytest.approx(81.55,abs=.005,rel=0)
    assert path.read_bytes() == original
