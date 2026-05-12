from __future__ import annotations

from gp_assistant.core.paths import store_dir
from gp_assistant.kernel import facade as k
from gp_assistant.gateway.app import app
from fastapi.testclient import TestClient
from gp_assistant.validation.strategy_health import save_strategy_health
from gp_assistant.selection_engine.artifact_store import persist_artifact_v2
from gp_assistant.portfolio.store import portfolio_state_path


def _cleanup():
    # remove validation summary and portfolio to force fallback
    p = store_dir() / 'validation' / 'latest_summary.json'
    if p.exists():
        p.unlink()
    pp = portfolio_state_path()
    if pp.exists():
        pp.unlink()
    ev = pp.parent / 'events.jsonl'
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


def test_workbench_fallback_and_aggregation():
    _cleanup()
    save_strategy_health('S_OKW', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid = '2099-08-01-WB'
    items = [{'pick_id':f'{rid}:A','symbol':'A','strategy':'S_OKW','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid, items)
    # API
    c = TestClient(app)
    r = c.get('/api/workbench', params={'as_of': rid})
    assert r.status_code == 200
    j = r.json()
    assert 'recommend' in j and 'portfolio' in j and 'validation_summary' in j and 'execution_events' in j
    # blocked rec should not become admissible intent
    save_strategy_health('S_KW', {'status':'killed','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    rid2 = '2099-08-01-WB2'
    items2 = [{'pick_id':f'{rid2}:B','symbol':'B','strategy':'S_KW','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]}]
    _persist_art(rid2, items2)
    snap = k.get_workbench_snapshot(as_of=rid2)
    prev = snap.get('intents_preview') or []
    assert not any(it.get('symbol')=='B' for it in prev)
