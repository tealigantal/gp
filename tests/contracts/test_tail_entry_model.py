"""Explicit integration tests: synthetic fixtures ONLY here, never a data fallback."""
import json
from pathlib import Path
import pytest
from gp_assistant.llm.client import LLMClient
from .test_tail_entry import bars, clock, setup


@pytest.mark.integration
@pytest.mark.parametrize("name,closes,actions,trends", [
    ("day_up_tail_weak", [10.9,10.8,10.7,10.6,10.5,10.4,10.3], {"do_not_enter", "wait"}, {"weakening"}),
    ("day_down_repair", [9.3,9.4,9.5,9.6,9.7,9.8,9.9], {"do_not_enter", "wait"}, {"repairing", "strengthening"}),
    ("strength_inside", [10.2,10.3,10.4,10.5,10.6,10.7,10.8], {"consider_entry"}, {"strengthening"}),
    ("pullback", [10.2,10.4,10.6,10.7,10.65,10.6,10.58], {"wait", "consider_entry"}, {"pullback", "mixed"}),
    ("spike_reversal", [10.4,10.6,10.9,10.7,10.5,10.3,10.1], {"do_not_enter", "wait"}, {"weakening"}),
    ("strength_above_zone", [11.1,11.2,11.3,11.4,11.5,11.6,11.7], {"do_not_enter"}, {"strengthening"}),
    ("mixed", [10.4,10.5,10.4,10.5,10.4,10.5,10.4], {"wait"}, {"mixed", "sideways"}),
])
def test_real_current_model_interprets_recent_evidence(tmp_path, suspension_calendar, name, closes, actions, trends):
    model = LLMClient()
    assert model.available()[0], "real configured model is required for this explicit integration run"
    store, p, service, _, _ = setup(tmp_path, suspension_calendar, model=model)
    frame = bars("14:40", closes)
    # Keep benchmark independent and flat; do not manufacture supporting volume.
    benchmark = bars("14:40", [10.5] * 7)
    result = service.assess(plan_id=p.plan_id, symbol="000001", scenario="new_position", now=clock(), mode="historical", frame=frame, benchmark=benchmark, fetched_at=clock(17))
    folder = Path("results/tail-entry-experiment-20260927")
    folder.mkdir(parents=True, exist_ok=True)
    report = folder / f"tail-model-synthetic-{name}.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    assert result["state"] == "historical", result
    verdict = result["assessment"]["judgment"]
    assert verdict["action"] in actions, verdict
    assert verdict["trend"] in trends, verdict
