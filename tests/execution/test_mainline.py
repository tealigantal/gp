from __future__ import annotations

from gp_assistant.core.paths import store_dir
from gp_assistant.kernel import facade as k
from gp_assistant.validation.strategy_health import save_strategy_health
from gp_assistant.selection_engine.artifact_store import persist_artifact_v2
from gp_assistant.portfolio.store import portfolio_state_path


def _rm_portfolio():
    p = portfolio_state_path()
    if p.exists():
        p.unlink()
    root = p.parent
    ev = root / 'events.jsonl'
    if ev.exists():
        ev.unlink()


def _persist_art(run_id: str, items):
    obj = {
        'run_id': run_id,
        'as_of': run_id,
        'degraded': False,
        'tradeable': True,
        'symbols': [it['symbol'] for it in items],
        'themes': [],
        'items': items,
        'artifact_version': 'v2',
        'fallback_used': False,
    }
    persist_artifact_v2(run_id, obj)


def test_blocked_item_produces_no_intent():
    save_strategy_health('S_K', {'status':'killed','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid = '2099-07-01-BLK'
    items = [{'pick_id':f'{rid}:X','symbol':'X','strategy':'S_K','execution_state':'actionable','actionable':True,'reward_risk':1.0,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid, items)
    gated = k.get_gated_artifact_v2(as_of=rid)
    intents = k.build_order_intents(as_of=rid)
    assert len(intents) == 0, f"unexpected intents for blocked: {gated}"


def test_degraded_item_has_reduced_priority():
    save_strategy_health('S_D', {'status':'degraded','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid = '2099-07-01-DGR'
    items = [{'pick_id':f'{rid}:Y','symbol':'Y','strategy':'S_D','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid, items)
    intents = k.build_order_intents(as_of=rid)
    assert len(intents) == 1
    assert intents[0]['priority'] < 1.0
    assert intents[0]['sizing_hint'] < 1.0
    assert intents[0]['gating_decision']['decision'] == 'degraded'


def test_allow_item_normal_intent():
    save_strategy_health('S_OK7', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid = '2099-07-01-ALW'
    items = [{'pick_id':f'{rid}:Z','symbol':'Z','strategy':'S_OK7','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid, items)
    intents = k.build_order_intents(as_of=rid)
    assert len(intents) == 1
    assert intents[0]['priority'] == 1.0


def test_missing_portfolio_store_fallback():
    _rm_portfolio()
    pf = k.get_portfolio_state()
    assert 'positions' in pf and 'pending_intents' in pf


def test_run_paper_execution_generates_events_and_pending():
    _rm_portfolio()
    save_strategy_health('S_OK8', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid = '2099-07-01-PE'
    items = [{'pick_id':f'{rid}:Q','symbol':'Q','strategy':'S_OK8','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid, items)
    res = k.run_paper_execution(as_of=rid)
    assert res.get('ok') is True and res.get('admitted', 0) >= 1
    pf = k.get_portfolio_state()
    assert len(pf.get('pending_intents') or []) >= 1


def test_execution_only_consumes_gated():
    # killed strategy -> should not appear in intents
    save_strategy_health('S_K2', {'status':'killed','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid = '2099-07-01-GV'
    items = [{'pick_id':f'{rid}:W','symbol':'W','strategy':'S_K2','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid, items)
    intents = k.build_order_intents(as_of=rid)
    assert intents == []


def test_missing_validation_summary_stable():
    p = store_dir() / 'validation' / 'latest_summary.json'
    if p.exists():
        p.unlink()
    # healthy strategy even without summary file should still build intent
    save_strategy_health('S_OK9', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid = '2099-07-01-MS'
    items = [{'pick_id':f'{rid}:R','symbol':'R','strategy':'S_OK9','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid, items)
    intents = k.build_order_intents(as_of=rid)
    assert len(intents) == 1
