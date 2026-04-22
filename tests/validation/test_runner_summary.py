from __future__ import annotations

import json
from pathlib import Path

from gp_assistant.validation.runner import run_validation_refresh
from gp_assistant.kernel.facade import get_validation_summary
from gp_assistant.gateway.app import app
from fastapi.testclient import TestClient


def test_validation_runner_and_summary_generation(tmp_path=None):
    res = run_validation_refresh()
    assert 'ok' in res and 'summary_path' in res
    p = Path(res['summary_path'])
    assert p.exists()
    data = json.loads(p.read_text(encoding='utf-8'))
    assert 'as_of' in data and 'parts' in data
    # live_shadow section present even when not available
    assert 'live_shadow' in (data.get('parts') or {})

    # facade read
    s2 = get_validation_summary()
    assert 'parts' in s2

    # API endpoint
    c = TestClient(app)
    r = c.get('/api/validation/summary')
    assert r.status_code == 200
    j = r.json()
    assert 'parts' in j
