from __future__ import annotations

import os
from typing import Any, Dict

import pytest


def test_history_store_upsert_does_not_overwrite_params(monkeypatch):
    from gp_assistant.search.history_store import ensure_query, query_meta, upsert_items

    import os, time
    base = os.path.abspath("store_test_" + str(int(time.time())))
    os.makedirs(base, exist_ok=True)
    monkeypatch.setenv("GP_STORE_DIR", base)
    qid = "test-qid-1"
    ensure_query(qid, {"a": 1})
    upsert_items(qid, [], id_key="id", time_key="time")
    meta = query_meta(qid)
    assert meta.get("params") == {"a": 1}


def test_history_store_upsert_creates_query_when_missing(monkeypatch):
    from gp_assistant.search.history_store import query_meta, upsert_items

    import os, time
    base = os.path.abspath("store_test_" + str(int(time.time())) + "_3")
    os.makedirs(base, exist_ok=True)
    monkeypatch.setenv("GP_STORE_DIR", base)
    qid = "qid-new"
    upsert_items(qid, [], id_key="id", time_key="time")
    meta = query_meta(qid)
    assert meta.get("params") == {}


def test_orchestrator_recommend_card_contains_meta_themes(monkeypatch):
    # isolate store
    import os, time
    base = os.path.abspath("store_test_" + str(int(time.time())) + "_2")
    os.makedirs(base, exist_ok=True)
    monkeypatch.setenv("GP_STORE_DIR", base)
    # monkeypatch recommend_run used by orchestrator
    import gp_assistant.chat.orchestrator as orch

    def fake_run(**kwargs: Any) -> Dict[str, Any]:
        return {
            "as_of": "2099-01-01",
            "timezone": "Asia/Shanghai",
            "env": {"grade": "C"},
            "themes": [{"name": "半导体", "strength": "1.23%"}],
            "picks": [{"symbol": "sz000001", "trade_plan": {"bands": {"S1": 10, "R1": 12}}}],
            "tradeable": True,
            "message": "ok",
            "execution_checklist": [],
            "disclaimer": "",
            "debug": {"degraded": False},
        }

    monkeypatch.setattr(orch, "recommend_run", fake_run)

    # call orchestrator
    data = orch.handle_message(session_id=None, message="推荐一下")
    assert isinstance(data, dict)

    # latest event must contain payload.meta.themes (list)
    from gp_assistant.chat import event_store

    # find latest conversation id
    convs = event_store.list_conversations()
    assert len(convs) >= 1
    cid = convs[-1]["id"]
    evs = event_store.list_events_after(cid, 0, limit=200)
    found = False
    for e in evs[::-1]:
        d = e.get("data") or {}
        if d.get("kind") == "card" and (d.get("payload") or {}).get("type") == "recommendation":
            meta = (d.get("payload") or {}).get("meta")
            assert isinstance(meta, dict)
            assert isinstance(meta.get("themes"), list)
            assert meta.get("as_of") is not None
            found = True
            break
    assert found


def test_orchestrator_writes_card_even_when_picks_empty(monkeypatch):
    import os, time
    base = os.path.abspath("store_test_" + str(int(time.time())) + "_4")
    os.makedirs(base, exist_ok=True)
    monkeypatch.setenv("GP_STORE_DIR", base)

    import gp_assistant.chat.orchestrator as orch

    def fake_run(**kwargs: Any) -> Dict[str, Any]:
        return {
            "as_of": "2099-01-01",
            "timezone": "Asia/Shanghai",
            "env": {"grade": "C"},
            "themes": [],
            "picks": [],
            "tradeable": False,
            "message": "empty",
            "execution_checklist": [],
            "disclaimer": "",
            "debug": {"degraded": True},
        }

    monkeypatch.setattr(orch, "recommend_run", fake_run)
    data = orch.handle_message(session_id=None, message="推荐一下")
    assert isinstance(data, dict)
    from gp_assistant.chat import event_store
    convs = event_store.list_conversations()
    assert len(convs) >= 1
    cid = convs[-1]["id"]
    evs = event_store.list_events_after(cid, 0, limit=200)
    found = False
    for e in evs[::-1]:
        d = e.get("data") or {}
        if d.get("kind") == "card" and (d.get("payload") or {}).get("type") == "recommendation":
            meta = (d.get("payload") or {}).get("meta")
            assert isinstance(meta, dict)
            assert isinstance(meta.get("themes"), list)
            assert meta.get("as_of") is not None
            found = True
            break
    assert found


def test_orchestrator_error_payload_has_data_status(monkeypatch):
    import os, time
    base = os.path.abspath("store_test_" + str(int(time.time())) + "_5")
    os.makedirs(base, exist_ok=True)
    monkeypatch.setenv("GP_STORE_DIR", base)

    import gp_assistant.chat.orchestrator as orch

    def raise_run(**kwargs: Any):
        raise RuntimeError("boom")

    monkeypatch.setattr(orch, "recommend_run", raise_run)
    data = orch.handle_message(session_id=None, message="推荐一下")
    assert isinstance(data, dict)
    from gp_assistant.chat import event_store
    convs = event_store.list_conversations()
    assert len(convs) >= 1
    cid = convs[-1]["id"]
    evs = event_store.list_events_after(cid, 0, limit=200)
    found = False
    for e in evs[::-1]:
        d = e.get("data") or {}
        if d.get("kind") == "card" and (d.get("payload") or {}).get("type") == "recommendation":
            meta = (d.get("payload") or {}).get("meta")
            assert isinstance(meta, dict)
            ds = meta.get("data_status")
            assert isinstance(ds, dict)
            assert (ds.get("snapshot") or {}).get("ok") is False
            assert (ds.get("snapshot") or {}).get("error") is not None
            assert isinstance(meta.get("themes"), list)
            found = True
            break
    assert found
