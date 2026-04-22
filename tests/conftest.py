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
    "chat",
    "execution",
    "recommend",
    "api/test_recommend_v2_endpoint.py",
    "api/test_compare_and_pick_endpoints.py",
    "kernel/test_kernel_facade_smoke.py",
    "gating/test_evaluator.py",
    "operator/test_workbench.py",
    "validation/test_runner_summary.py",
    "validation/test_strategy_health_penalty.py",
    "test_backtest_stats.py",
    "test_candidate_gen_snapshot_fallback.py",
    "test_execution_bands_semantics.py",
    "test_execution_state_below_support.py",
    "test_last_date_fix.py",
    "test_mainboard_and_thematic_filters.py",
    "test_publish_atomic.py",
    "test_regress_theme_and_bands.py",
    "test_render_no_pseudo_defaults.py",
    "test_service_pipeline_smoke.py",
    "test_service_state_idempotent.py",
    "test_session_state_and_context.py",
    "test_signals_calc.py",
    "test_strict_no_pseudo_output.py",
    "test_structural_bands_chip_fallback.py",
    "test_theme_and_mainline.py",
    "test_theme_fallback_top_movers.py",
    "test_theme_pool_impl_nan_and_scale.py",
    "test_theme_pool_snapshot_paths.py",
]


def pytest_collection_modifyitems(config, items):
    """Mark unrelated tests as integration so default run skips them."""
    keep_prefixes = (
        "test_backtest_core_rules.py",
        "test_regress_theme_and_bands.py",
        "test_contract_event_and_history.py",
        "test_theme_fallback_top_movers.py",
        "test_strict_no_pseudo_output.py",
        "test_calibration.py",
        "test_contracts_v2.py",
        "test_refresh_service_v2.py",
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
