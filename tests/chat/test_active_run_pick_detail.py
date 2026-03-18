from __future__ import annotations

import json
from pathlib import Path
from fastapi.testclient import TestClient
from gp_assistant.server.app import app
from gp_assistant.chat import session_store as store


def _persist_v2(run_id: str, items: list[dict]):
    base = Path('store/recommend')
    base.mkdir(parents=True, exist_ok=True)
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
    (base / f'{run_id}_v2.json').write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def test_analyze_uses_pick_detail_from_active_run():
    run_id = '2099-01-02'
    items = [
        {'symbol': 'ZZZ', 'execution_state': 'waiting_pullback', 'actionable': False, 'entry_zone': [10, 12], 'stop': 9.5, 'take_profit': [13.5]},
        {'symbol': 'YYY', 'execution_state': 'actionable', 'actionable': True, 'entry_zone': [20, 21], 'stop': 19.5, 'take_profit': [22.5]},
    ]
    _persist_v2(run_id, items)
    sid = store.ensure_session('c_run')
    store.update_state(sid, { 'active_run_id': run_id, 'active_symbols': ['ZZZ','YYY'] })
    c = TestClient(app)
    r = c.post('/api/chat', json={ 'session_id': sid, 'message': '第二只' })
    assert r.status_code == 200
    j = r.json()
    # should include pick detail numbers from YYY
    assert '20' in j.get('reply') or '21' in j.get('reply')

