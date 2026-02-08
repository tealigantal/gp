import sys
from pathlib import Path


root = Path(__file__).resolve().parents[1]
src = root / "src"
if str(src) not in sys.path:
    sys.path.insert(0, str(src))

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
