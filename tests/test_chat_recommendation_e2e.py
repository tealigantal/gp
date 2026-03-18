from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.server.app import app


def _runid(j):
    ctx = j.get('followup_context') or {}
    return ctx.get('active_run_id') or j.get('run_id')


def test_scene_normal_recommend_and_why():
    c = TestClient(app)
    r1 = c.post('/api/chat', json={'message': '给我推荐3只'})
    j1 = r1.json()
    rid = _runid(j1)
    assert rid
    # 第二只 -> same run
    r2 = c.post('/api/chat', json={'session_id': j1['session_id'], 'message': '第二只'})
    j2 = r2.json()
    assert _runid(j2) == rid
    # 为什么推荐它 -> same run
    r3 = c.post('/api/chat', json={'session_id': j1['session_id'], 'message': '为什么推荐它'})
    j3 = r3.json()
    assert _runid(j3) == rid
    assert isinstance(j3.get('reply'), str)


def test_scene_no_trade_explain_stable():
    c = TestClient(app)
    r1 = c.post('/api/chat', json={'message': '给我推荐3只'})
    j1 = r1.json()
    rid = _runid(j1)
    assert rid
    r2 = c.post('/api/chat', json={'session_id': j1['session_id'], 'message': '为什么空仓'})
    j2 = r2.json()
    assert _runid(j2) == rid
    assert isinstance(j2.get('reply'), str)


def test_scene_refresh_new_run():
    c = TestClient(app)
    r1 = c.post('/api/chat', json={'message': '给我推荐3只'})
    j1 = r1.json()
    rid1 = _runid(j1)
    assert rid1
    r2 = c.post('/api/chat', json={'session_id': j1['session_id'], 'message': '重新算'})
    j2 = r2.json()
    rid2 = _runid(j2)
    assert rid2 and rid2 != rid1
    # 后续追问跟随新 run
    r3 = c.post('/api/chat', json={'session_id': j1['session_id'], 'message': '第二只'})
    j3 = r3.json()
    assert _runid(j3) == rid2

