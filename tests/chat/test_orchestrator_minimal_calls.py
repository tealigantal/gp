from __future__ import annotations

import json

from gp_assistant.core.paths import store_dir
from gp_assistant.chat import session_store as store
from gp_assistant.chat.orchestrator import handle_message


def _write_artifact(run_id: str, trading_date: str, symbol: str) -> None:
    base = store_dir() / "recommend"
    base.mkdir(parents=True, exist_ok=True)
    obj = {
        "artifact_version": "v2",
        "run_id": run_id,
        "as_of": trading_date,
        "trading_date": trading_date,
        "as_of_ts": f"{trading_date}T20:00:00",
        "data_cutoff": "EOD",
        "symbols": [symbol],
        "themes": [],
        "items": [
            {
                "pick_id": f"{run_id}:{symbol}",
                "symbol": symbol,
                "actionable": True,
                "take_profit": [1.0],
                "reward_risk": 1.0,
            }
        ],
        "degraded": False,
        "tradeable": True,
    }
    (base / f"{run_id}_v2.json").write_text(json.dumps(obj), encoding="utf-8")


def test_pick_detail_no_redundant_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("STORE_ROOT", str(tmp_path))
    run_id = "run_ref"
    symbol = "600519"
    _write_artifact(run_id, "2024-03-08", symbol)

    sid = store.ensure_session(None)
    store.update_state(sid, {"referenced_run_id": run_id, "focused_symbol": symbol})

    # Count kernel gating calls and runner runs
    calls = {"gated": 0, "run": 0}

    import gp_assistant.kernel.facade as facade
    import gp_assistant.recommend.artifact_store as astore
    real_get = facade.get_gated_artifact_v2

    def _fake_get_gated(run_id=None, as_of=None):  # noqa: ANN001
        calls["gated"] += 1
        return real_get(run_id=run_id, as_of=as_of)

    monkeypatch.setattr(facade, "get_gated_artifact_v2", _fake_get_gated)

    import gp_assistant.recommend.runner as runner

    def _fake_run(**kwargs):  # noqa: ANN001
        calls["run"] += 1
        return {"as_of": "2024-03-11", "picks": []}

    monkeypatch.setattr(runner, "run", _fake_run)

    _ = handle_message(sid, "这只还能买吗", None)
    assert calls["run"] == 0
    assert calls["gated"] <= 2

