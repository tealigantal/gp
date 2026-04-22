from __future__ import annotations

import json
from pathlib import Path


def test_service_preopen_uses_engine(monkeypatch, tmp_path: Path):
    # Change CWD
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'store' / 'recommend').mkdir(parents=True, exist_ok=True)

    # Monkeypatch engine.run to deterministic picks
    from src.gp_assistant.selection_engine import engine as eng

    def fake_engine_run(date=None, topk=3, universe="auto", symbols=None, risk_profile="normal"):  # noqa: ANN001
        return {
            "as_of": "20250106",
            "picks": [
                {"symbol": "600519", "candidate_score": 1.0, "champion": {"strategy": "S1", "score": 1.0}},
                {"symbol": "000001", "candidate_score": 0.9, "champion": {"strategy": "S1", "score": 0.8}},
            ],
            "meta": {"debug": {}},
        }

    monkeypatch.setattr(eng, "run", fake_engine_run)

    # Execute service preopen
    from src.service.pipeline import service_preopen

    service_preopen("20250106", topk=2)

    latest = json.loads((tmp_path / 'store' / 'recommend' / 'latest.json').read_text(encoding='utf-8'))
    assert isinstance(latest, dict)
    picks = latest.get("picks") or []
    assert len(picks) == 2
    # ensure order matches engine (600519 first)
    assert str(picks[0].get("symbol")) in {"600519", "sh600519"}

