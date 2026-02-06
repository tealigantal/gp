from __future__ import annotations

def test_llm_proxy_app_import(monkeypatch):
    # Ensure the llm-proxy package can be imported and exposes app
    import sys
    sys.path.insert(0, 'services/llm_proxy')
    from llm_proxy.app import app  # type: ignore
    assert app is not None
