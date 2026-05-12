from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.core.paths import store_dir
from gp_assistant.kernel import facade as k
from gp_assistant.gateway.app import app
from gp_assistant.validation.strategy_health import save_strategy_health
from gp_assistant.validation.walkforward_stats import save_walkforward
from gp_assistant.selection_engine.artifact_store import persist_artifact_v2


def _rm_summary():
    p = store_dir() / 'validation' / 'latest_summary.json'
    if p.exists():
        p.unlink()


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


def test_item_killed_blocked():
    _rm_summary()
    save_strategy_health('TMP_K6', {'status':'killed','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    run_id = '2099-06-01-K6'
    items = [{
        'pick_id': f'{run_id}:X','symbol':'X','strategy':'TMP_K6',
        'execution_state':'actionable','actionable':True,
        'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[],
    }]
    _persist_art(run_id, items)
    art = k.get_gated_artifact_v2(as_of=run_id)
    dec = (art['items'][0].get('gating_decision') or {}).get('decision')
    assert dec == 'blocked'


def test_item_degraded_by_health():
    _rm_summary()
    save_strategy_health('TMP_D6', {'status':'degraded','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    run_id = '2099-06-01-D6'
    items = [{
        'pick_id': f'{run_id}:X','symbol':'X','strategy':'TMP_D6',
        'execution_state':'actionable','actionable':True,
        'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[],
    }]
    _persist_art(run_id, items)
    art = k.get_gated_artifact_v2(as_of=run_id)
    dec = (art['items'][0].get('gating_decision') or {}).get('decision')
    assert dec == 'degraded'


def test_item_invalidated_blocked():
    _rm_summary()
    save_strategy_health('TMP_H6', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    run_id = '2099-06-01-I6'
    items = [{
        'pick_id': f'{run_id}:X','symbol':'X','strategy':'TMP_H6',
        'execution_state':'actionable','actionable':True,
        'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':True,'invalidation':['close_below_S1'],
    }]
    _persist_art(run_id, items)
    art = k.get_gated_artifact_v2(as_of=run_id)
    dec = (art['items'][0].get('gating_decision') or {}).get('decision')
    assert dec == 'blocked'


def test_run_degraded_missing_walkforward():
    _rm_summary()
    # two strategies with missing walkforward -> degrade run
    save_strategy_health('S_A', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    save_strategy_health('S_B', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    run_id = '2099-06-01-R6'
    items = [
        {'pick_id': f'{run_id}:A','symbol':'A','strategy':'S_A','execution_state':'actionable','actionable':True,'reward_risk':0.5,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
        {'pick_id': f'{run_id}:B','symbol':'B','strategy':'S_B','execution_state':'actionable','actionable':True,'reward_risk':0.6,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
    ]
    _persist_art(run_id, items)
    art = k.get_gated_artifact_v2(as_of=run_id)
    run_dec = (art.get('run_gating') or {}).get('decision')
    assert run_dec == 'degraded'


def test_live_shadow_unavailable_is_advisory():
    _rm_summary()
    # Provide walkforward for single strategy so run doesn't degrade
    save_strategy_health('S_OK', {'status':'healthy','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    save_walkforward('S_OK', {"windows": [0.01], "stable": True, "recent_rank": 1})
    run_id = '2099-06-01-LS6'
    items = [{
        'pick_id': f'{run_id}:X','symbol':'X','strategy':'S_OK','execution_state':'actionable','actionable':True,'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]
    }]
    _persist_art(run_id, items)
    art = k.get_gated_artifact_v2(as_of=run_id)
    run_dec = (art.get('run_gating') or {}).get('decision')
    # Should remain allow (walkforward present), but warnings contain live_shadow_unavailable
    assert run_dec == 'allow'
    assert 'live_shadow_unavailable' in ((art.get('run_gating') or {}).get('warnings') or [])


def test_compare_excludes_blocked_from_winner():
    _rm_summary()
    save_strategy_health('TMP_KC', {'status':'killed','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    run_id = '2099-06-01-C6'
    items = [
        {'pick_id': f'{run_id}:X','symbol':'X','strategy':'TMP_KC','execution_state':'actionable','actionable':True,'reward_risk':0.9,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
        {'pick_id': f'{run_id}:Y','symbol':'Y','strategy':'S_OK2','execution_state':'actionable','actionable':True,'reward_risk':0.5,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
    ]
    _persist_art(run_id, items)
    comp = k.compare_symbols(run_id, ['X','Y'])
    assert comp.get('winner_symbol') == 'Y'


def test_pick_detail_contains_gating_reasons():
    _rm_summary()
    save_strategy_health('TMP_KP', {'status':'killed','reason_codes':[],'paper_trade_summary':{},'event_summary':{},'walkforward_summary':{}})
    run_id = '2099-06-01-P6'
    items = [{
        'pick_id': f'{run_id}:X','symbol':'X','strategy':'TMP_KP',
        'execution_state':'actionable','actionable':True,
        'reward_risk':0.8,'liquidity_grade':'A','invalidated_now':False,'invalidation':[],
    }]
    _persist_art(run_id, items)
    det = k.get_pick_detail(run_id, 'X')
    it = det.get('item') or {}
    gd = it.get('gating_decision') or {}
    assert gd.get('decision') == 'blocked'
    assert any('strategy_health' in r for r in (gd.get('reasons') or []))


def test_missing_summary_file_graceful_fallback():
    _rm_summary()
    s = k.get_validation_summary()
    assert 'parts' in s
    # API also stable
    c = TestClient(app)
    r = c.get('/api/validation/summary')
    assert r.status_code == 200
    assert 'parts' in (r.json())
