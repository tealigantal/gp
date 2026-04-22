from __future__ import annotations


def test_mainline_does_not_read_latest_json_directly():
    import inspect
    from gp_assistant.chat_compat.orchestrator import handle_message
    src = inspect.getsource(handle_message)
    assert "latest.json" not in src
