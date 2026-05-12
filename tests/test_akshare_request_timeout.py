from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import requests

from gp_assistant.providers.akshare_provider import AkShareProvider


def test_requests_timeout_patch_is_concurrency_safe(monkeypatch):
    calls: list[float | None] = []
    original = requests.sessions.Session.request

    def fake_request(session, method, url, **kwargs):
        time.sleep(0.01)
        calls.append(kwargs.get("timeout"))
        return "ok"

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)
    provider = AkShareProvider(timeout_sec=3)

    def run_once():
        return provider._with_requests_timeout(lambda: requests.Session().request("GET", "https://quote.eastmoney.com/test"))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: run_once(), range(20)))

    assert results == ["ok"] * 20
    assert requests.sessions.Session.request is fake_request
    assert all(value is not None and value >= 3 for value in calls)
    assert original is not fake_request
