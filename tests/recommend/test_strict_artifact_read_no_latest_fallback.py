from __future__ import annotations

import json

import pytest

from gp_assistant.core.paths import store_dir
from gp_assistant.kernel.facade import get_artifact_v2


def test_strict_read_does_not_use_latest(monkeypatch, tmp_path):
    monkeypatch.setenv("STORE_ROOT", str(tmp_path))
    base = store_dir() / "recommend"
    base.mkdir(parents=True, exist_ok=True)
    # Write latest files which strict read must not use implicitly
    latest = {
        "artifact_version": "v2",
        "run_id": "latest-run",
        "as_of": "2024-03-08",
        "trading_date": "2024-03-08",
        "as_of_ts": "2024-03-08T20:00:00",
        "data_cutoff": "EOD",
        "symbols": [],
        "themes": [],
        "items": [],
        "degraded": False,
        "tradeable": True,
    }
    (base / "latest_v2.json").write_text(json.dumps(latest), encoding="utf-8")
    (base / "latest.json").write_text(json.dumps({"as_of": "2024-03-08", "picks": []}), encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        _ = get_artifact_v2()

