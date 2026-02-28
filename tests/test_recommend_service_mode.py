from __future__ import annotations

import json
from pathlib import Path


def _write_latest(tmp_path: Path, picks: list[dict] | None = None) -> None:
    (tmp_path / 'store' / 'recommend').mkdir(parents=True, exist_ok=True)
    latest = {
        "as_of": "2025-01-06 09:20:00",
        "timezone": "Asia/Shanghai",
        "tradeable": True,
        "message": "preopen",
        "disclaimer": "",
        "stage": "preopen",
        "picks": picks if picks is not None else [
            {"symbol": "sz000001", "name": "平安银行", "theme": "金融", "champion": {"strategy": "baseline"}, "trade_plan": {"bands": {"S1": 10, "R1": 12}}, "tags": []}
        ],
        "debug": {"mode": "service", "degraded": False, "reasons": []},
    }
    (tmp_path / 'store' / 'recommend' / 'latest.json').write_text(json.dumps(latest, ensure_ascii=False), encoding='utf-8')


def test_service_mode_reads_latest(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_latest(tmp_path)
    from src.gp_assistant.recommend.runner import run as recommend_run

    out = recommend_run(mode="service")
    assert isinstance(out, dict)
    assert isinstance(out.get("picks"), list) and len(out["picks"]) >= 1
    dbg = out.get("debug") or {}
    assert (dbg or {}).get("mode") == "service"
    # ensure required fields exist
    assert isinstance(out.get("themes"), list)
    assert isinstance(out.get("mainline"), dict)
    assert isinstance(out.get("data_status"), dict)


def test_orchestrator_handles_latest_keyword(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    _write_latest(tmp_path)

    import src.gp_assistant.chat.orchestrator as orch
    data = orch.handle_message(session_id=None, message="最新推荐")
    assert isinstance(data, dict)
    from src.gp_assistant.chat import event_store
    convs = event_store.list_conversations()
    assert len(convs) >= 1
    cid = convs[-1]["id"]
    evs = event_store.list_events_after(cid, 0, limit=200)
    found = False
    for e in evs[::-1]:
        d = e.get("data") or {}
        if d.get("kind") == "card" and (d.get("payload") or {}).get("type") == "recommendation":
            found = True
            break
    assert found

