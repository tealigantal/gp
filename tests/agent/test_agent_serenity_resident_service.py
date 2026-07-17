from pathlib import Path

import pytest
import yaml

from gp_assistant.core.config import SerenityConfig
from gp_assistant.decision_engine.serenity_policy import effective_weight
from gp_assistant.serenity.models import SerenityPolicyState


def test_serenity_config_is_native_by_default_and_retires_legacy_modes():
    assert SerenityConfig().mode == "native"
    with pytest.raises(ValueError, match="invalid GP_SERENITY_MODE"):
        SerenityConfig(mode="auto")
    with pytest.raises(ValueError, match="invalid GP_SERENITY_MODE"):
        SerenityConfig(mode="reference")
    assert SerenityConfig(mode="off").mode == "off"


def test_native_mode_uses_the_stored_weight_only_for_an_active_bootstrapped_state():
    state = SerenityPolicyState(
        state="active",
        applied_weight=0.08,
        max_weight=0.08,
        state_since="2026-07-13T00:00:00+08:00",
        updated_at="2026-07-13T00:00:00+08:00",
        bootstrap_run_id="legacy-bootstrap",
    )

    assert effective_weight(state, mode="native") == 0.08
    assert effective_weight(state, mode="off") == 0.0


def test_serenity_is_a_default_compose_service():
    compose_path = Path(__file__).resolve().parents[2] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    service = compose["services"]["gp-serenity-worker"]

    assert "profiles" not in service
    assert service["command"] == ["python", "-m", "gp_assistant.cli", "serenity-loop"]
    assert compose["x-gp-env"]["GP_SERENITY_MODE"] == "${GP_SERENITY_MODE:-native}"
