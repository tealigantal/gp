import os
import json
from typing import Any, Dict

os.environ.setdefault("STRICT_REAL_DATA", "0")
os.environ.setdefault("TZ", "Asia/Shanghai")

from fastapi.testclient import TestClient  # noqa: E402

from gp_assistant.server.app import app  # noqa: E402


client = TestClient(app)


def test_health_api_and_legacy():
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ["status", "llm_ready", "provider", "time"]:
        assert k in data

    # legacy still available
    r2 = client.get("/health")
    assert r2.status_code == 200


def test_recommend_compact_and_full():
    body = {
        "topk": 1,
        "universe": "symbols",
        "symbols": ["600519"],
        # 不传 detail，默认 compact
    }
    r = client.post("/api/recommend", json=body)
    assert r.status_code == 200, r.text
    comp = r.json()
    # 默认 compact 不应包含 candidate_pool（若算法返回该字段）
    assert "candidate_pool" not in comp
    for k in ["as_of", "env", "themes", "picks", "tradeable", "message"]:
        assert k in comp

    body_full = dict(body)
    body_full["detail"] = "full"
    r2 = client.post("/api/recommend", json=body_full)
    assert r2.status_code == 200, r2.text
    full = r2.json()
    # full 至少比 compact 多一个字段：要么 candidate_pool，要么 debug 更丰富
    more = False
    if "candidate_pool" in full:
        more = True
    else:
        comp_dbg = comp.get("debug", {}) if isinstance(comp.get("debug"), dict) else {}
        full_dbg = full.get("debug", {}) if isinstance(full.get("debug"), dict) else {}
        if len(full_dbg) > len(comp_dbg):
            more = True
    assert more, "full 响应未体现更丰富字段"


def test_openapi_no_legacy_paths():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths: Dict[str, Any] = r.json().get("paths", {})
    # 旧路由不应出现
    for p in ["/health", "/chat", "/recommend"]:
        assert p not in paths, f"legacy path leaked: {p}"
    # 新路由应该存在
    for p in ["/api/health", "/api/chat", "/api/recommend"]:
        assert p in paths


def test_recommend_by_date_404():
    r = client.get("/api/recommend/2099-01-01")
    assert r.status_code == 404


def test_ohlcv_limit_10_no_500():
    r = client.get("/api/ohlcv/000001", params={"limit": 10})
    # 允许 200 或 4xx，但不能 500
    assert r.status_code < 500
    if r.status_code == 200:
        data = r.json()
        assert "bars" in data and isinstance(data["bars"], list)
        if data["bars"]:
            bar = data["bars"][0]
            for k in ["date", "open", "high", "low", "close", "volume", "amount"]:
                assert k in bar

