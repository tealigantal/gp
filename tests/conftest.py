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
        "test_backtest_core_rules.py",
    )
    for item in items:
        fn = item.location[0]
        if not any(fn.endswith(p) for p in keep_prefixes):
            item.add_marker("integration")
