import sys
from pathlib import Path


root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Ignore out-of-scope tests that depend on external frameworks or services
collect_ignore = [
    "test_agent_pick_mock.py",
    "test_agent_pick_once_mock.py",
    "test_asof_guard.py",
    "test_assistant_security.py",
    "test_cli_output_string_only.py",
    "test_constraints_core.py",
    "test_json_protocol_flow.py",
    "test_llm_proxy_import.py",
    "test_llm_proxy_smoke.py",
    "test_pipeline_mock.py",
    "test_prompt_prefix_clean.py",
    "test_require_trades.py",
    "test_strategies_minute.py",
    "test_imports_compile.py",
    "test_session_state.py",
]


def pytest_collection_modifyitems(config, items):
    """Mark unrelated tests as integration so default run skips them.

    Keep core backtest/selector tests enabled; mark the rest as integration.
    """
    keep_prefixes = (
        # 保持为默认非 integration（CI/本地默认都会跑）
        "test_backtest_core_rules.py",
        # CI 回归用例白名单（见 .github/workflows/ci.yml）
        "test_regress_theme_and_bands.py",
        "test_contract_event_and_history.py",
        "test_theme_fallback_top_movers.py",
        "test_theme_pool_snapshot_paths.py",
        "test_theme_pool_impl_nan_and_scale.py",
        "test_strict_no_pseudo_output.py",
        # Phase 2.6 gate additions
        "test_calibration.py",
        "test_contracts_v2.py",
        "test_refresh_service_v2.py",
        "test_recommend_v2_endpoint.py",
        "test_compare_and_pick_endpoints.py",
        # Phase 3 gate additions (validation)
        "test_event_stats.py",
        "test_walkforward_stats.py",
        "test_paper_trade.py",
        "test_strategy_health.py",
        "test_lifecycle.py",
        "test_validation_endpoints.py",
    )
    for item in items:
        fn = item.location[0]
        if not any(fn.endswith(p) for p in keep_prefixes):
            item.add_marker("integration")
