from __future__ import annotations

import json
from pathlib import Path

from gp_assistant.core.paths import store_dir
from gp_assistant.chat_compat import session_store as store
from gp_assistant.chat_compat.orchestrator import handle_message


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


def test_followup_does_not_refresh(monkeypatch, tmp_path):
    # Isolate store
    monkeypatch.setenv("STORE_ROOT", str(tmp_path))
    _write_artifact("run_old", "2024-03-08")

    sid = store.ensure_session(None)
    store.update_state(sid, {"referenced_run_id": "run_old"})

    calls = {"n": 0}

    def _fake_run(**kwargs):  # noqa: ANN001
        calls["n"] += 1
        return {"as_of": "2024-03-11", "picks": []}

    import gp_assistant.selection_engine.runner as runner

    monkeypatch.setattr(runner, "run", _fake_run)

    # Follow-up style question should not trigger new run
    handle_message(sid, "缁楊兛绨╅崣顏冭礋娴犫偓娑?, None)
    assert calls["n"] == 0

    # Explicit refresh triggers recomputation
    handle_message(sid, "閸掗攱鏌?, None)
    assert calls["n"] == 1
