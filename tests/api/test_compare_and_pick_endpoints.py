from __future__ import annotations

from pathlib import Path
import json
from fastapi.testclient import TestClient
from gp_assistant.server.app import app


def _persist_minimal_v2(as_of: str) -> None:
    base = Path('store/recommend')
    base.mkdir(parents=True, exist_ok=True)
    obj = {
        'run_id': as_of,
        'as_of': as_of,
        'degraded': False,
        'tradeable': True,
        'symbols': ['AAA','BBB'],
        'themes': [],
        'items': [
            {'pick_id': f'{as_of}:AAA','symbol':'AAA','execution_state':'actionable','actionable':True,'reward_risk':0.3,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
            {'pick_id': f'{as_of}:BBB','symbol':'BBB','execution_state':'actionable','actionable':True,'reward_risk':1.2,'liquidity_grade':'A','invalidated_now':False,'invalidation':[]},
        ],
        'artifact_version':'v2','fallback_used': False,
    }
    p = base / f'{as_of}_v2.json'
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def test_compare_and_pick():
    as_of = '2099-01-04'
    _persist_minimal_v2(as_of)
    client = TestClient(app)
    # compare
    r = client.post('/api/compare', json={'run_id': as_of, 'symbols': ['AAA','BBB']})
    assert r.status_code == 200
    cj = r.json()
    assert cj.get('ok') in (True, False)
    assert 'fallback_used' in cj
    # pick detail
    r2 = client.get('/api/pick', params={'run_id': as_of, 'symbol': 'AAA'})
    assert r2.status_code == 200
    j2 = r2.json()
    assert 'ok' in j2
