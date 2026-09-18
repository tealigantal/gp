"""Frozen-input policy comparison, never inverse inference or a return backtest.

Input is a read-only exported snapshot: plan, mature event_pool, dated frames,
evidence_day, knowledge_time and maintenance context. No database is opened.
The old formula exists here only as the explicitly labelled audit comparator.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics

import pandas as pd

from gp_assistant.application.real_producer import RealRecommendationProducer
from gp_assistant.core.paths import configs_dir
from gp_assistant.decision_engine.adaptive import AdaptiveDecisionEngine
from gp_assistant.decision_engine.scoring import ROUND_TRIP_COST, load_scoring_policy
from gp_assistant.market_memory.retrieval import retrieve_similar_events
from gp_assistant.market_memory.store import MarketMemoryEvent
from gp_assistant.probability_engine.engine import infer_probability
from gp_assistant.risk_engine.engine import assess_candidate_risk
from gp_assistant.signal_engine.daily import build_signal_events_for_symbol


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def summary(values):
    ordered = sorted(values)
    def percentile(q):
        pos = (len(ordered)-1)*q
        lo = int(pos)
        return ordered[lo] + (ordered[min(lo+1,len(ordered)-1)]-ordered[lo])*(pos-lo)
    return dict(count=len(values), minimum=min(values), p10=percentile(.1), p25=percentile(.25),
                median=percentile(.5), p75=percentile(.75), p90=percentile(.9), maximum=max(values), mean=statistics.mean(values))


def compare(snapshot: Path):
    data = json.loads(snapshot.read_text(encoding="utf-8-sig"))
    pool = [MarketMemoryEvent(**e) for e in data["event_pool"]]
    day = data["evidence_day"]
    known = datetime.fromisoformat(data["knowledge_time"])
    config = json.loads((configs_dir()/"daily_scoring.json").read_text(encoding="utf-8"))
    # The policy was frozen later: this is explicitly a counterfactual on one
    # immutable input, NOT a claim it was available to the historical plan.
    policy = load_scoring_policy(evidence_day=day, known_at=datetime.fromisoformat(config["reference"]["frozen_at"]))
    records = []
    for e in sorted(pool,key=lambda e:e.event_id):
        assert e.outcome_complete and e.outcome["complete"] is True
        assert e.signal_trading_day < day and e.outcome_available_trading_day < day
        assert datetime.fromisoformat(e.first_seen_at) <= known
        r = e.outcome["return_3d"]
        assert math.isfinite(r)
        records.append(dict(event_id=e.event_id,signal_trading_day=e.signal_trading_day,
            outcome_available_trading_day=e.outcome_available_trading_day,first_seen_at=e.first_seen_at,return_3d=r,cost=ROUND_TRIP_COST))
    assert datetime.fromisoformat(data["maintenance"]["completed_at"]) <= known
    assert len({r["event_id"] for r in records}) == len(records)
    a0 = math.fsum(abs(r["return_3d"]-r["cost"]) for r in records)/len(records)
    assert digest(records) == config["reference"]["source_digest"]
    assert a0 == policy.a0
    frames = {symbol:pd.DataFrame(rows) for symbol,rows in data["frames"].items()}
    assert all(str(frame["date"].max())[:10] <= day for frame in frames.values())
    context = data["maintenance"]["context"]
    new = RealRecommendationProducer(None)._candidates(frames,day,known_at=known,
        market_context=context,event_pool=pool,scoring_policy=policy)
    by_symbol = {c.symbol:c for c in new}
    rows, deviations = [], []
    for old in data["plan"]["evaluated_candidates"]:
        symbol = old["symbol"]
        event = build_signal_events_for_symbol(symbol=symbol,df=frames[symbol],as_of=day,market_context=context,max_history=0).current_event
        retrieval = retrieve_similar_events(event,as_of=day,event_pool=pool)
        p = infer_probability(current_event=event.__dict__,retrieval=retrieval)
        risk = assess_candidate_risk(signal=event.__dict__,probability=p)
        old_score = max(0.,min(1.,.5*p["up_probability_3d"]+.3*risk["execution_quality"]+.2*p["confidence"]-.2*p["drawdown_probability"]))
        serenity = sum(e["contribution"] for e in old["experts"] if e["expert"]=="serenity")
        deviations.append(abs(max(0.,min(1.,old_score+serenity))-old["adaptive_score"]))
        assert abs(p["expected_return_3d"]-old["probability"]["expected_return_3d"]) < 1e-12
        c = by_symbol[symbol]
        r = c.ranking
        rows.append(dict(symbol=symbol,old_score=old_score*100,new_score=c.adaptive_score*100,
            G=r.gain,L=r.loss,N=r.support,A0=r.a0,n0=r.n0,net_return=c.probability.expected_net_return,
            case_digest=digest(retrieval["cases"]),case_count=len(retrieval["cases"]),date_count=len({x["as_of"] for x in retrieval["cases"]})))
    assert max(deviations) < 1e-12, "frozen_inputs_do_not_reproduce_published_plan"
    old_order = sorted(rows,key=lambda r:(-r["old_score"],r["symbol"]))
    old_chosen = [r["symbol"] for r in old_order[:30] if r["old_score"]>=50 and r["net_return"]>0][:3]
    new_top30 = frozenset(c.symbol for c in sorted(new,key=lambda c:(-c.adaptive_score,c.symbol))[:30])
    selected = AdaptiveDecisionEngine().select(new,selection_eligible_symbols=new_top30)
    new_chosen = [c.symbol for c in selected if c.disposition.value=="selected"]
    return dict(method="Same frozen mature cases and dated prices; actual new producer vs old v5 formula reproduced against immutable revision4 plan. Zero Serenity on both comparison lanes because Top30 changes. Counterfactual score comparison, not historical deployment or return backtest.",
        plan_id=data["plan"]["plan_id"],evidence_day=day,knowledge_time=data["knowledge_time"],
        policy_frozen_at=policy.frozen_at.isoformat(),case_pool_count=len(pool),reference_digest=digest(records),
        case_digest=data["case_digest"],price_digest=data["price_digest"],a0=a0,n0=policy.n0,
        old_published_score_max_reproduction_error=max(deviations),
        old=summary([r["old_score"] for r in rows]),new=summary([r["new_score"] for r in rows]),
        old_top3=old_chosen,new_top3=new_chosen,top30_overlap=len(new_top30 & {r["symbol"] for r in old_order[:30]}),
        examples=[r for r in rows if r["symbol"] in set(old_chosen+new_chosen)],candidates=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot",type=Path)
    print(json.dumps(compare(parser.parse_args().snapshot),ensure_ascii=False,indent=2,allow_nan=False))
