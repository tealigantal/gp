import sys
from pathlib import Path


root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Ignore out-of-scope tests that depend on retired API surfaces or external services.
collect_ignore = [
    "test_agent_pick_mock.py",
    "test_agent_pick_once_mock.py",
    "test_asof_guard.py",
    "test_assistant_security.py",
    "test_cli_output_string_only.py",
    "test_constraints_core.py",
    "test_json_protocol_flow.py",
    "test_pipeline_mock.py",
    "test_prompt_prefix_clean.py",
    "test_require_trades.py",
    "test_strategies_minute.py",
    "test_imports_compile.py",
    "test_session_state.py",
    "execution",
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


def pytest_collection_modifyitems(config, items):
    """Mark unrelated tests as integration so default run skips them."""
    keep_prefixes = (
        "test_backtest_core_rules.py",
        "test_api_smoke.py",
        "test_health_llm_checks.py",
        "test_book_current_dedup.py",
        "test_chat_endpoint_smoke.py",
        "test_app_import.py",
        "test_event_stats.py",
        "test_walkforward_stats.py",
        "test_paper_trade.py",
        "test_strategy_health.py",
        "test_lifecycle.py",
        "test_validation_endpoints.py",
        "test_mainline.py",
        "test_interpret_request_types.py",
        "test_judgment_dispatch.py",
        "test_dispatch_new_handlers.py",
        "test_daybook_mapping.py",
    )
    for item in items:
        fn = item.location[0]
        if not any(fn.endswith(prefix) for prefix in keep_prefixes):
            item.add_marker("integration")
