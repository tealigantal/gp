from __future__ import annotations

import json
from pathlib import Path

from gp_assistant.core.paths import store_dir
from gp_assistant.chat import session_store as store
from gp_assistant.chat.run_service import resolve_referenced_run


def _write_artifact(run_id: str, trading_date: str) -> None:
    base = store_dir() / "recommend"
    base.mkdir(parents=True, exist_ok=True)
    obj = {
        "artifact_version": "v2",
        "run_id": run_id,
        "as_of": trading_date,
        "trading_date": trading_date,
        "as_of_ts": f"{trading_date}T20:00:00",
        "data_cutoff": "EOD",
        "symbols": [],
        "themes": [],
        "items": [],
        "degraded": False,
        "tradeable": True,
    }
    (base / f"{run_id}_v2.json").write_text(json.dumps(obj), encoding="utf-8")


def test_referenced_run_preferred_over_active(tmp_path, monkeypatch):
    # ensure store_dir points to temp
    monkeypatch.setenv("STORE_ROOT", str(tmp_path))
    _write_artifact("run_old", "2024-03-08")
    _write_artifact("run_new", "2024-03-11")

    sid = store.ensure_session(None)
    store.update_state(sid, {"active_run_id": "run_new", "referenced_run_id": "run_old"})

    ref = resolve_referenced_run(sid)
    assert ref.get("resolved_run_id") == "run_old"

    # Change active_run_id; referenced should still hold
    store.update_state(sid, {"active_run_id": "run_new"})
    ref2 = resolve_referenced_run(sid)
    assert ref2.get("resolved_run_id") == "run_old"

