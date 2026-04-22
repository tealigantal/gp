from __future__ import annotations

import json
from pathlib import Path
from fastapi.testclient import TestClient

from gp_assistant.kernel import facade as k
from gp_assistant.gateway.app import app
from gp_assistant.selection_engine.artifact_store import persist_artifact_v2


def _persist_minimal(run_id: str) -> None:
    base = Path('store/recommend')
    base.mkdir(parents=True, exist_ok=True)
    obj = {
        'run_id': run_id,
        'as_of': run_id,
        'degraded': False,
        'tradeable': True,
        'symbols': ['AAA','BBB'],
        'themes': [],
        'items': [
            {'pick_id': f'{run_id}:AAA','symbol':'AAA','execution_state':'actionable','actionable':True,'reward_risk':0.3,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
            {'pick_id': f'{run_id}:BBB','symbol':'BBB','execution_state':'actionable','actionable':True,'reward_risk':1.2,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
        ],
        'artifact_version':'v2','fallback_used': False,
    }
    persist_artifact_v2(run_id, obj)


def test_kernel_facade_unified_run_id():
    run_id = '2099-03-01'
    _persist_minimal(run_id)

    art = k.get_artifact_v2(as_of=run_id)
    assert art.get('run_id') == run_id

    comp = k.compare_symbols(run_id, ['AAA','BBB'])
    assert comp.get('run_id') == run_id
    assert comp.get('ranking') in (['BBB','AAA'], ['AAA','BBB'])

    pd = k.get_pick_detail(run_id, 'AAA')
    assert pd.get('run_id') == run_id and pd.get('item',{}).get('symbol') == 'AAA'

    # Endpoints reflect the same artifact
    c = TestClient(app)
    r1 = c.get('/api/recommend_v2', params={'as_of': run_id})
    assert r1.status_code == 200 and r1.json().get('run_id') == run_id
    r2 = c.post('/api/compare', json={'run_id': run_id, 'symbols': ['AAA','BBB']})
    assert r2.status_code == 200 and r2.json().get('run_id') == run_id
    r3 = c.get('/api/pick', params={'run_id': run_id, 'symbol': 'AAA'})
    assert r3.status_code == 200 and r3.json().get('run_id') == run_id

    # Validation / live shadow facade presence
    sv = k.get_strategy_validation('S1')
    assert 'event_stats' in sv and 'walk_forward' in sv and 'strategy_health' in sv
    ls = k.get_live_shadow_latest_summary()
    assert 'available' in ls and 'dates' in ls
