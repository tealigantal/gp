from datetime import datetime, timedelta, timezone
import sqlite3

import pandas as pd
import pytest

from gp_assistant.market_memory import maintenance as m
from gp_assistant.market_memory.store import list_events_before
from gp_assistant.decision_engine.scoring import score_candidate
from gp_assistant.decision_engine.adaptive import AdaptiveDecisionEngine
from gp_assistant.application.real_producer import RealRecommendationProducer
from tests.contracts.test_serenity_fixed_weight import _candidate
from types import SimpleNamespace


def history(n=150):
    dates = pd.bdate_range("2025-12-01", periods=n).strftime("%Y-%m-%d")
    return pd.DataFrame(dict(date=dates, close=[10+i*.02 for i in range(n)],
        open=[10+i*.02 for i in range(n)], high=[10.1+i*.02 for i in range(n)],
        low=[9.9+i*.02 for i in range(n)],volume=[1000.]*n,amount=[1e9]*n))


def test_mature_memory_idempotent_causal_and_scope_bound(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    first = history()
    target = first.iloc[-1]["date"]
    monkeypatch.setattr(m, "frames", lambda symbols, **kw: {s: first.copy() for s in symbols})
    before = datetime.now(timezone.utc)-timedelta(seconds=1)
    report = m.maintain(target=target,symbols=("000001","000002"),now=before)
    assert report["state"] == "complete"
    assert m.ready(target,("000002","000001"),("000001","000002"))["run_id"] == report["run_id"]
    with pytest.raises(ValueError,match="pending"):
        m.ready(target,("000001",),("000001",))
    assert list_events_before(target,known_at=before,policy=m.POLICY) == []
    known = datetime.now(timezone.utc)+timedelta(seconds=1)
    original = list_events_before(target,known_at=known,policy=m.POLICY)
    assert len(original) > 80
    assert all(e.outcome_complete and e.outcome_available_trading_day < target for e in original)
    assert m.maintain(target=target,symbols=("000001","000002"),now=known) == report
    next_frame = history(151)
    monkeypatch.setattr(m,"frames",lambda symbols,**kw:{s:next_frame.copy() for s in symbols})
    m.maintain(target=next_frame.iloc[-1]["date"],symbols=("000001","000002"),now=known)
    updated = list_events_before(next_frame.iloc[-1]["date"],known_at=datetime.now(timezone.utc)+timedelta(seconds=1),policy=m.POLICY)
    assert len(updated) == len(original)+2
    by_id = {e.event_id:e for e in updated}
    assert all(by_id[e.event_id] == e for e in original)


def test_incomplete_target_cannot_complete_memory(tmp_path,monkeypatch):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    data = history()
    monkeypatch.setattr(m,"frames",lambda *a,**kw:{"000001":data,"000002":data.iloc[:-1]})
    with pytest.raises(ValueError,match="target_coverage_incomplete"):
        m.maintain(target=data.iloc[-1]["date"],symbols=("000001","000002"),now=datetime.now(timezone.utc))
    assert list_events_before(data.iloc[-1]["date"], known_at=datetime.now(timezone.utc), policy=m.POLICY) == []
    with pytest.raises(ValueError,match="pending"):
        m.ready(data.iloc[-1]["date"],("000001","000002"),("000001","000002"))


def test_invalid_history_is_not_silently_defaulted():
    frame=history()
    frame.loc[5,"close"]=float("nan")
    with pytest.raises(ValueError,match="invalid_bar"):
        m.contexts({"000001":frame})


def test_cost_gate_cannot_be_overridden_by_serenity():
    score = score_candidate(probability=.8,execution_quality=.8,confidence=.9,drawdown_probability=.1,expected_return=.002)
    assert score["expected_net_return"] < 0
    candidate=_candidate("000001",score["score"])
    candidate=candidate.model_copy(update={"ranking":candidate.ranking.model_copy(update={"reason_codes":score["reason_codes"]})})
    fused=RealRecommendationProducer._apply_serenity((candidate,),SimpleNamespace(applied_weight=.03,alphas={"000001":1.},reasons={},reason_codes=()))
    result=AdaptiveDecisionEngine().select(fused)
    assert result[0].disposition.value != "selected"
    assert fused[0].ranking.score == fused[0].adaptive_score


def test_trade_plan_stop_is_below_entire_entry_zone():
    from gp_assistant.risk_engine.engine import assess_candidate_risk
    risk = assess_candidate_risk(signal={"features":{"close":40.,"support":37.,"atr_pct":.02}},
        probability={"expected_return_3d":.01,"drawdown_probability":.2,"confidence":.8})
    assert 0 < risk['stop']['price'] < risk['entry']['low'] <= risk['entry']['high'] < risk['take_profit']['price']
    assert risk['diagnostics']['reward_risk'] == pytest.approx((risk['take_profit']['price']-risk['entry']['high'])/(risk['entry']['high']-risk['stop']['price']))


def test_partial_batch_hidden_and_changed_input_restarts(tmp_path, monkeypatch):
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    data = history()
    monkeypatch.setattr(m, "frames", lambda symbols, **kw: {s: data.copy() for s in symbols})
    original = m.upsert_market_events
    calls = []
    def interrupt(events):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("interrupted")
        return original(events)
    monkeypatch.setattr(m, "upsert_market_events", interrupt)
    target = data.iloc[-1]["date"]
    now = datetime.now(timezone.utc)
    with pytest.raises(RuntimeError, match="interrupted"):
        m.maintain(target=target, symbols=("000001","000002"), now=now)
    assert list_events_before(target, known_at=datetime.now(timezone.utc), policy=m.POLICY) == []
    data.loc[10, "volume"] += 1
    monkeypatch.setattr(m, "upsert_market_events", original)
    report = m.maintain(target=target, symbols=("000001","000002"), now=now)
    assert report["state"] == "complete"
    events = list_events_before(target, known_at=datetime.now(timezone.utc), policy=m.POLICY)
    assert len(events) > 160
    assert len({(e.symbol,e.signal_trading_day) for e in events}) == len(events)
    assert list_events_before(target, known_at=now, policy=m.POLICY) == []
    # Restoring A after replacement B committed must not revive duplicate
    # staged versions from A's checkpoint.
    data.loc[10, "volume"] -= 1
    m.maintain(target=target, symbols=("000001","000002"), now=now)
    resumed = list_events_before(target, known_at=datetime.now(timezone.utc), policy=m.POLICY)
    assert {(e.symbol,e.signal_trading_day):e for e in resumed} == {(e.symbol,e.signal_trading_day):e for e in events}
    assert len(resumed) == len(events)
