"""Tests of production functions. The 2% reference below is a math fixture only."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import math
from types import SimpleNamespace

import pandas as pd
import pytest

from gp_assistant.application import real_producer as producer
from gp_assistant.contracts.evidence import RankingAssessment
from gp_assistant.decision_engine.adaptive import AdaptiveDecisionEngine
from gp_assistant.decision_engine.scoring import REVISION, ScoringPolicy, load_scoring_policy, score_candidate
from gp_assistant.probability_engine.engine import infer_probability
from tests.contracts.test_serenity_fixed_weight import _candidate


def case(index, net, *, similarity=1.0, day=None, cost=.003):
    return dict(event_id=f"e{index}", as_of=day or (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
                similarity=similarity, outcome=dict(complete=True, return_3d=net + cost))


def infer(cases, cost=.003):
    return infer_probability(current_event={}, retrieval={"cases": cases}, modeled_cost=cost)


def score(g=.02, l=.01, n=64., a0=.02, n0=20.):
    return score_candidate(gain=g, loss=l, support=n, a0=a0, n0=n0)["score"]


@pytest.mark.parametrize("gain,loss,expected", [(.05,.01,80.1),(.03,.02,61.8),(.02,.02,53.8),(.01,.03,34.2)])
def test_math_fixtures_are_not_production_calibration(gain, loss, expected):
    assert score(g=.55*gain, l=.45*loss)*100 == pytest.approx(expected, abs=.05)


@pytest.mark.parametrize("g,l", [(0.,0.),(.01,.01),(.03,0.),(0.,.03),(1e-12,0.),(1e300,1e300)])
def test_finite_bounds_balance_and_monotonicity(g,l):
    result = score(g,l)
    assert math.isfinite(result) and 0 <= result <= 1
    if g == l:
        assert result == pytest.approx(.5)
    assert score(g+.01,l) >= result
    assert score(g,l+.01) <= result


@pytest.mark.parametrize("g,l", [(.03,.005),(.005,.03)])
def test_less_support_shrinks_good_and_bad_towards_half(g,l):
    values = [score(g,l,n) for n in [64,20,1,.01]]
    assert all(abs(b-.5) < abs(a-.5) for a,b in zip(values,values[1:]))
    assert all((v-.5)*(g-l)>0 for v in values)


def test_case_cost_increases_cannot_improve_score_with_fixed_support():
    cases = [case(0,.03),case(1,-.01),case(2,.001),case(3,0.)]
    results = [infer(cases,cost=c) for c in [0.,.001,.003,.01,.1]]
    assert len({r["support"] for r in results}) == 1
    values = [score(r["gain"],r["loss"],r["support"]) for r in results]
    assert all(b <= a for a,b in zip(values,values[1:]))
    for r in results:
        assert r["expected_net_return"] == r["gain"]-r["loss"]


def test_deduplication_date_support_and_similarity_mean():
    cases = [case(0,.02,similarity=.5,day="2026-01-01"),case(1,-.01,similarity=1.,day="2026-01-01"),case(2,.03,similarity=.5,day="2026-01-02")]
    original = infer(cases)
    repeated = infer(cases + [deepcopy(cases[0])] * 50)
    for key in ["gain","loss","support","expected_net_return","up_probability_3d"]:
        assert original[key] == repeated[key]
    assert original["evidence"]["sample_size"] == 3
    date_n = 1/(.75**2+.25**2)
    assert original["evidence"]["date_support"] == pytest.approx(date_n)
    assert date_n <= 2
    assert original["support"] == pytest.approx(date_n * (2/3))
    assert original["gain"] == pytest.approx(.25*.02+.25*.03)
    assert original["loss"] == pytest.approx(.5*.01)
    conflict = deepcopy(cases[0]); conflict["outcome"]["return_3d"] += .01
    with pytest.raises(ValueError,match="event_conflict"):
        infer(cases+[conflict])


@pytest.mark.parametrize("net", [0.,.01,-.01,1e-12])
def test_one_case_and_all_profit_loss_or_true_zero(net):
    for cases in [[case(0,net)], [case(i,net,day="2026-01-01") for i in range(30)]]:
        r = infer(cases)
        assert r["support"] == pytest.approx(1.)
        value = score(r["gain"],r["loss"],r["support"])
        assert (value == .5) if net == 0 else ((value-.5)*net > 0)


@pytest.mark.parametrize("field,value", [("return_3d",None),("return_3d",float("nan")),("return_3d",float("inf")),("similarity",-1.),("similarity",float("nan")),("similarity",2.),("as_of","2026-02-30"),("as_of",None),("event_id",None),("complete",False)])
def test_invalid_required_cases_fail_explicitly(field,value):
    row = case(0,.02)
    (row["outcome"] if field in {"return_3d","complete"} else row)[field] = value
    with pytest.raises(ValueError,match="case_"):
        infer([row])


def test_empty_missing_and_zero_weight_are_not_normal_half_scores():
    for cases in [[],[case(0,.01,similarity=0.)]]:
        with pytest.raises(ValueError,match="evidence_unavailable"):
            infer(cases)
    row = case(0,.01); del row["outcome"]["return_3d"]
    with pytest.raises(ValueError,match="return_3d_invalid"):
        infer([row])


def test_valid_zero_similarity_remains_in_arithmetic_mean():
    result = infer([case(0,.02,similarity=1.),case(1,-.03,similarity=0.)])
    assert result["gain"] == pytest.approx(.02)
    assert result["loss"] == 0.
    assert result["evidence"]["date_support"] == 1.
    assert result["evidence"]["mean_similarity"] == .5
    assert result["support"] == .5


@pytest.mark.parametrize("kwargs", [dict(n=0),dict(n=-1),dict(a0=0),dict(a0=-.1),dict(n0=0),dict(g=-.1),dict(l=-.1),dict(g=float("inf")),dict(a0=float("nan"))])
def test_invalid_score_inputs(kwargs):
    with pytest.raises(ValueError):
        score(**kwargs)


def test_real_producer_records_reproducible_score_and_applies_serenity_once(monkeypatch):
    cases = [case(i,.03 if i%2 else -.01,similarity=.8) for i in range(80)]
    signal = SimpleNamespace(features={"close":10.,"amount":1e9}, signal_type="structure_watch")
    monkeypatch.setattr(producer,"build_signal_events_for_symbol",lambda **kw:SimpleNamespace(current_event=signal))
    monkeypatch.setattr(producer,"retrieve_similar_events",lambda *a,**kw:{"cases":cases})
    policy = ScoringPolicy(.02,20.,"fixture",datetime.now(timezone.utc),date(2026,1,1))
    candidates = producer.RealRecommendationProducer(None)._candidates(
        {"000001":pd.DataFrame([{"amount":1e9}])}, "2026-06-01",known_at=datetime.now(timezone.utc),market_context={},event_pool=cases,scoring_policy=policy)
    c = candidates[0]; r = c.ranking
    assert r.core_score == r.score == c.adaptive_score == score(r.gain,r.loss,r.support,r.a0,r.n0)
    assert c.probability.expected_net_return == r.gain-r.loss
    assert c.probability.expected_return_3d-.003 == pytest.approx(r.gain-r.loss)
    decision = SimpleNamespace(applied_weight=.03,alphas={c.symbol:1.},reasons={},reason_codes=())
    once = producer.RealRecommendationProducer._apply_serenity(candidates,decision)
    twice = producer.RealRecommendationProducer._apply_serenity(once,decision)
    assert once == twice
    assert once[0].adaptive_score == r.core_score+.03
    assert once[0].ranking.score == once[0].adaptive_score
    assert once[0].probability == c.probability
    assert len(once[0].experts) == 1
    zero = producer.RealRecommendationProducer._apply_serenity(twice,SimpleNamespace(**{**decision.__dict__,"applied_weight":0.}))
    assert zero[0].adaptive_score == r.core_score


def test_selector_top_three_observations_without_threshold_but_with_scope_and_restriction():
    rows = tuple(_candidate(f"{i:06d}", .49-i*.05) for i in range(6))
    rows = tuple(c.model_copy(update={"ranking":c.ranking.model_copy(update={"reason_codes":("nonpositive_net_edge",)})}) for c in rows)
    rows = (*rows[:1],rows[1].model_copy(update={"trade_plan":rows[1].trade_plan.model_copy(update={"action":"suspended"})}),*rows[2:])
    chosen = AdaptiveDecisionEngine().select(rows,maximum_selected=99,selection_eligible_symbols=frozenset(c.symbol for c in rows[1:]))
    assert [c.symbol for c in chosen if c.disposition.value=="selected"] == ["000002","000003","000004"]
    assert all("nonpositive_net_edge" in c.ranking.reason_codes for c in chosen)
    with pytest.raises(ValueError,match="score_invalid"):
        AdaptiveDecisionEngine().select((rows[0].model_copy(update={"adaptive_score":float("nan")}),))


@pytest.mark.parametrize("core,alpha,expected", [(.99,1.,1.),(.01,-1.,0.)])
def test_serenity_clipping_and_reapplication_keep_one_actual_contribution(core,alpha,expected):
    c = _candidate("000001",core)
    c = c.model_copy(update={"ranking":c.ranking.model_copy(update={"core_score":core})})
    decision = SimpleNamespace(applied_weight=.03,alphas={c.symbol:alpha},reasons={},reason_codes=())
    once = producer.RealRecommendationProducer._apply_serenity((c,),decision)
    assert producer.RealRecommendationProducer._apply_serenity(once,decision) == once
    assert once[0].adaptive_score == once[0].ranking.score == expected
    assert once[0].experts[0].contribution == expected-core


def test_policy_time_boundary_and_missing_reference(tmp_path,monkeypatch):
    monkeypatch.setenv("GP_CONFIGS_DIR",str(tmp_path))
    payload = dict(revision=REVISION,n0=20.,a0=.02,round_trip_cost=.003,
                   reference=dict(frozen_at="2026-09-18T08:00:00+00:00",evidence_date="2026-09-17",case_count=10,source_digest="fixture"))
    path = tmp_path/"daily_scoring.json"
    path.write_text(json.dumps(payload))
    now = datetime(2026,9,19,tzinfo=timezone.utc)
    p = load_scoring_policy(evidence_day="2026-09-18",known_at=now)
    payload["n0"]=21.; path.write_text(json.dumps(payload))
    assert load_scoring_policy(evidence_day="2026-09-18",known_at=now).digest != p.digest
    with pytest.raises(ValueError,match="not_yet_available"):
        load_scoring_policy(evidence_day="2026-09-16",known_at=now)
    with pytest.raises(ValueError,match="not_yet_available"):
        load_scoring_policy(evidence_day="2026-09-18",known_at=datetime(2026,9,17,tzinfo=timezone.utc))
    payload["a0"]=None; path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match="reference_unavailable"):
        load_scoring_policy(evidence_day="2026-09-18",known_at=now)


def test_old_ranking_missing_fields_are_unrecorded():
    ranking = RankingAssessment.model_validate(dict(score=.6,rank=1,reason_codes=[]))
    assert all(getattr(ranking,key) is None for key in ("gain","loss","support","a0","n0","core_score","policy_revision"))


def test_new_policy_and_producer_never_reuse_or_rewrite_old_plan(tmp_path):
    from gp_assistant.store import ContractStore
    from gp_assistant.application.plan_service import PlanService
    from gp_assistant.application.target_resolver import resolve_plan_target
    from gp_assistant.contracts.market import TradingCalendarRef
    from tests.contracts.test_contract_lifecycle import plan
    store = ContractStore(tmp_path/"contract.sqlite")
    old = plan(store)
    target = resolve_plan_target(now=old.generated_at,completed_daily_date=old.daily_evidence_date,
        calendar=TradingCalendarRef(calendar_id="cn",revision="1",source="fixture"),is_open=True,
        next_open_session=old.market_session_date,required_daily_evidence_date=old.daily_evidence_date)
    arguments = dict(target=target,universe=old.candidate_universe,
        policy=old.decision_policy.model_copy(update={"revision":REVISION,"adaptive_policy_state_version":"memory:new_policy_digest:serenity"}),
        producer=old.producer.model_copy(update={"revision":producer.DAILY_PRODUCER_REVISION}),
        evaluated_candidates=old.evaluated_candidates,serenity=old.serenity,generated_at=old.generated_at)
    new = PlanService(store).get_or_create(**arguments).plan
    assert new.plan_id != old.plan_id
    assert PlanService(store).get_or_create(**arguments).plan == new
    assert store.load_plan(old.plan_id) == old
    assert store.load_plan(old.plan_id).evaluated_candidates[0].ranking.gain is None


def test_scheduler_fast_reuse_checks_frozen_policy_digest(monkeypatch):
    from gp_assistant.application import market_orchestrator as module
    now = datetime(2026,9,18,16,tzinfo=timezone(timedelta(hours=8)))
    current = SimpleNamespace(producer=SimpleNamespace(revision=producer.DAILY_PRODUCER_REVISION),
        decision_policy=SimpleNamespace(revision=REVISION,adaptive_policy_state_version="memory:digest_one:serenity"),
        market_session_date=date(2026,9,21),daily_evidence_date=now.date())
    monkeypatch.setattr(module,"publication_ineligibility",lambda plan:None)
    monkeypatch.setattr(module,"scoring_policy_digest",lambda:"digest_one")
    class Rebuild(Exception):
        pass
    def rebuild(*args,**kwargs):
        raise Rebuild
    instance = SimpleNamespace(store=SimpleNamespace(current_publication=lambda:SimpleNamespace(plan_id="old"),load_plan=lambda _:current),
        _required_daily_date=lambda *_:now.date(),_serenity_upgrade_available=lambda *a,**kw:False,
        real=SimpleNamespace(produce=rebuild))
    arguments = dict(run=SimpleNamespace(trade_date=now.date().isoformat(),universe=object()),now=now,
                     calendar=SimpleNamespace(next_open_after=lambda _:date(2026,9,21)))
    module.MarketDayOrchestrator._publish_base_if_due(instance,**arguments)
    monkeypatch.setattr(module,"scoring_policy_digest",lambda:"digest_two")
    with pytest.raises(Rebuild):
        module.MarketDayOrchestrator._publish_base_if_due(instance,**arguments)
