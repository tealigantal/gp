import os
import sys
import tempfile
from pathlib import Path


root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

os.environ.setdefault("GP_RUNS_DIR", str(Path(tempfile.gettempdir()) / "gp-pytest-runs"))
os.environ.setdefault("GP_STORE_DIR", str(root / ".pytest-tmp" / "store"))

# Ignore out-of-scope tests that depend on retired API surfaces or external services.
# Files listed here are skipped before import, so default collection cannot be
# broken by retired or environment-dependent modules.
collect_ignore = [
    "test_agent_pick_mock.py",
    "test_agent_pick_once_mock.py",
    "test_asof_guard.py",
    "test_assistant_security.py",
    "test_assistant_canonical_workflow.py",
    "test_cli_output_string_only.py",
    "test_constraints_core.py",
    "test_json_protocol_flow.py",
    "test_pipeline_mock.py",
    "test_prompt_prefix_clean.py",
    "test_pulse5m_state_machine.py",
    "test_pulse_cross_day.py",
    "test_require_trades.py",
    "test_strategies_minute.py",
    "test_imports_compile.py",
    "test_session_state.py",
    "test_backtest_stats.py",
    "test_candidate_gen_snapshot_fallback.py",
    "test_execution_bands_semantics.py",
    "test_execution_state_below_support.py",
    "test_last_date_fix.py",
    "test_mainboard_and_thematic_filters.py",
    "test_publish_atomic.py",
    "test_service_pipeline_smoke.py",
    "test_service_state_idempotent.py",
    "test_signals_calc.py",
    "test_structural_bands_chip_fallback.py",
]


def pytest_ignore_collect(collection_path, config):  # noqa: ANN001
    """Retired V1/V2, run, Workbench and paper-execution tests are not importable.

    They are intentionally skipped before import rather than held as a hidden
    compatibility suite for deleted product surfaces.
    """
    path = str(collection_path).replace("\\", "/")
    if not path.endswith(".py"):
        return False
    restored = (
        "/tests/test_worker_reconcile.py",
        "/tests/test_daily_freshness.py",
        "/tests/test_history_store_journal_mode.py",
        "/tests/test_health_storage_stats.py",
        "/tests/test_compose_shared_backend.py",
        "/tests/test_llm_payload_shape.py",
        "/tests/test_serenity_narration_boundary.py",
        "/tests/test_serenity_policy.py",
        "/tests/test_serenity_runtime.py",
        "/tests/test_serenity_scheduler.py",
        "/tests/test_serenity_sources.py",
        "/tests/test_serenity_store.py",
        "/tests/decision_engine/test_adaptive_policy.py",
    )
    return "/tests/agent/" not in path and not path.endswith("/tests/server/test_single_chat_contract.py") and not path.endswith(restored)


def pytest_collection_modifyitems(config, items):
    """Only the unified product contract is part of the default suite."""
    keep_prefixes = (
        "test_agent_store.py", "test_engine_database_inputs.py", "test_market_time_storage_contract.py",
        "test_agent_serenity_resident_service.py",
        "test_agent_serenity_lease_recovery.py",
        "test_compose_shared_backend.py",
        "test_single_chat_contract.py", "test_worker_reconcile.py", "test_daily_freshness.py",
        "test_history_store_journal_mode.py", "test_health_storage_stats.py",
        "test_agent_llm_chat.py", "test_serenity_native_engine.py",
        "test_agent_native_snapshot_integrity.py",
        "test_daybook_native_projection.py",
        "test_llm_payload_shape.py", "test_serenity_narration_boundary.py",
        "test_serenity_policy.py", "test_serenity_runtime.py", "test_serenity_scheduler.py", "test_serenity_sources.py",
        "test_serenity_store.py", "test_adaptive_policy.py",
    )
    for item in items:
        fn = item.location[0]
        if not any(fn.endswith(prefix) for prefix in keep_prefixes):
            item.add_marker("integration")
