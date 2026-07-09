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
        "test_runner_summary.py",
        "test_strategy_health_penalty.py",
        "test_evaluator.py",
        "test_kernel_facade_smoke.py",
        "test_workbench.py",
        "test_mainline.py",
        "test_compare_and_pick_endpoints.py",
        "test_compare_endpoint.py",
        "test_pick_detail_endpoint.py",
        "test_recommend_v2_endpoint.py",
        "test_chg_normalize_inference.py",
        "test_theme_pool_impl_nan_and_scale.py",
        "test_theme_pool_snapshot_paths.py",
        "test_champion_affects_ranking_engine.py",
        "test_interpret_request_types.py",
        "test_judgment_dispatch.py",
        "test_dispatch_new_handlers.py",
        "test_single_stock_query.py",
        "test_card_tool_llm_explanation.py",
        "test_llm_semantic_layer.py",
        "test_freshness_policy.py",
        "test_daybook_mapping.py",
        "test_daily_freshness.py",
        "test_worker_reconcile.py",
        "test_health_runtime_status.py",
        "test_slot_state.py",
        "test_akshare_request_timeout.py",
        "test_runtime_lanes.py",
        "test_market_clock_slots.py",
        "test_intraday_multistrategy.py",
        "test_live_entry_quote_plan.py",
        "test_tail_strategy_enhancements.py",
        "test_market_memory_agent.py",
        "test_decision_intelligence.py",
    )
    for item in items:
        fn = item.location[0]
        if not any(fn.endswith(prefix) for prefix in keep_prefixes):
            item.add_marker("integration")
