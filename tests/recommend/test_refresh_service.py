from gp_assistant.chat import session_store as store
from gp_assistant.chat.refresh_service import refresh_symbols


def test_refresh_symbols_batch_preserves_collection():
    syms = ["AAA", "BBB", "CCC"]
    out = refresh_symbols(syms)
    # Even if refresh fails due to data unavailability in CI, the symbols should be echoed back deterministically
    assert isinstance(out, dict)
    assert out.get("symbols") == syms

