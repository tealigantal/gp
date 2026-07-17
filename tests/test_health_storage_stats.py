from __future__ import annotations

from fastapi.testclient import TestClient

from gp_assistant.agent_store import AgentStore
from gp_assistant.gateway.app import app
from gp_assistant.runtime.market_time import MarketTimeContext
from tests.agent.test_agent_store import make_book, make_pending_runtime


def test_health_reads_stats_and_current_pointer_in_one_snapshot(monkeypatch, tmp_path):
    db = tmp_path / "agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    AgentStore(db).publish_book(make_book("health-snapshot"))

    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["product_ready"] is False
    assert payload["readiness_reasons"]
    assert payload["llm"]["verification"] in {"not_configured", "unverified", "error"}
    assert payload["serenity"]["available"] is False
    assert payload["agent_db"]["current_snapshot_id"] == "health-snapshot"
    assert payload["current_snapshot"]["snapshot_id"] == "health-snapshot"
    assert payload["current_snapshot"]["decision_trade_day"] == "2026-07-13"


def test_health_is_ready_only_when_snapshot_runtime_serenity_and_llm_all_match(
    monkeypatch, tmp_path
):
    db = tmp_path / "ready-agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    market_time = MarketTimeContext(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day=None,
        pulse_slot_closed_at=None,
        observed_at="2026-07-13T10:00:00+08:00",
        market_phase="non_trading",
        target_mode="previous_completed",
    )
    book = make_book("ready-snapshot")
    target_id = str(book.daybook.source_meta["serenity_target_id"])
    AgentStore(db).publish_book(book, market_time=market_time)
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.resolve_daily_target", lambda **_kwargs: market_time
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.serenity_status_snapshot",
        lambda: {
            "available": True,
            "reason": None,
            "worker_alive": True,
            "candidate_target": {"target_id": target_id},
        },
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes._current_serenity_check",
        lambda _book: (
            None,
            {
                "available": True,
                "readiness_revision": "new-freshness-certificate",
                "semantic_revision": book.daybook.source_meta[
                    "serenity_semantic_revision"
                ],
            },
        ),
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.llm_status",
        lambda: {"verification": "ready", "verification_fresh": True},
    )

    payload = TestClient(app).get("/api/health").json()

    assert payload["status"] == "ok"
    assert payload["product_ready"] is True
    assert payload["readiness_reasons"] == []
    assert payload["worker"]["runtime_contract_ready"] is True
    assert payload["serenity"]["snapshot_readiness_revision"] != payload["serenity"]["active_readiness_revision"]
    assert payload["serenity"]["snapshot_semantic_revision"] == payload["serenity"]["active_semantic_revision"]


def test_health_degrades_when_same_target_has_new_serenity_semantics(
    monkeypatch, tmp_path
):
    db = tmp_path / "revision-agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    market_time = MarketTimeContext(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day=None,
        pulse_slot_closed_at=None,
        observed_at="2026-07-13T10:00:00+08:00",
        market_phase="non_trading",
        target_mode="previous_completed",
    )
    book = make_book("revision-snapshot")
    target_id = str(book.daybook.source_meta["serenity_target_id"])
    AgentStore(db).publish_book(book, market_time=market_time)
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.resolve_daily_target", lambda **_kwargs: market_time
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.serenity_status_snapshot",
        lambda: {
            "available": True,
            "reason": None,
            "worker_alive": True,
            "candidate_target": {"target_id": target_id},
        },
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes._current_serenity_check",
        lambda _book: (
            "current_serenity_semantic_revision_changed",
            {
                "available": False,
                "readiness_revision": "new-poll-revision",
                "semantic_revision": "new-semantic-revision",
            },
        ),
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.llm_status",
        lambda: {"verification": "ready", "verification_fresh": True},
    )

    payload = TestClient(app).get("/api/health").json()

    assert payload["status"] == "degraded"
    assert payload["product_ready"] is False
    assert any(
        "current_serenity_semantic_revision_changed" in reason
        for reason in payload["readiness_reasons"]
    )


def test_valid_pending_snapshot_is_pending_not_integrity_corruption(
    monkeypatch, tmp_path
):
    db = tmp_path / "pending-agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "market-memory"))
    monkeypatch.setenv("GP_SERENITY_STORE_DIR", str(tmp_path / "serenity"))
    daybook, artifact, _ = make_pending_runtime()
    market_time = MarketTimeContext(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day=None,
        pulse_slot_closed_at=None,
        observed_at="2026-07-13T10:00:00+08:00",
        market_phase="postclose_ready",
        target_mode="previous_completed",
    )
    AgentStore(db).publish_runtime_artifact(
        daybook, artifact, market_time=market_time
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.resolve_daily_target",
        lambda **_kwargs: market_time,
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes._current_serenity_check",
        lambda _book: ("current_serenity_target_missing", {}),
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.llm_status",
        lambda: {"verification": "ready", "verification_fresh": True},
    )

    payload = TestClient(app).get("/api/health").json()

    assert payload["product_ready"] is False
    assert any("等待 Serenity" in item for item in payload["readiness_reasons"])
    assert not any("完整性校验" in item for item in payload["readiness_reasons"])


def test_health_uses_exact_market_time_binding_when_current_slot_disappears(
    monkeypatch, tmp_path
):
    db = tmp_path / "slot-agent.db"
    monkeypatch.setenv("GP_AGENT_DB", str(db))
    stored_time = MarketTimeContext(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day="2026-07-13",
        pulse_slot_closed_at="2026-07-13T10:00:00+08:00",
        observed_at="2026-07-13T10:00:00+08:00",
        market_phase="intraday_am",
        target_mode="current_ready",
    )
    current_time = MarketTimeContext(
        decision_trade_day="2026-07-13",
        daybook_effective_day="2026-07-13",
        pulse_trade_day="2026-07-13",
        pulse_slot_closed_at=None,
        observed_at="2026-07-13T10:02:00+08:00",
        market_phase="intraday_am",
        target_mode="current_ready",
    )
    AgentStore(db).publish_book(
        make_book("slot-snapshot"), market_time=stored_time
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.resolve_daily_target",
        lambda **_kwargs: current_time,
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes._current_serenity_check",
        lambda _book: (None, {"available": True}),
    )
    monkeypatch.setattr(
        "gp_assistant.gateway.routes.llm_status",
        lambda: {"verification": "ready", "verification_fresh": True},
    )

    payload = TestClient(app).get("/api/health").json()

    assert payload["product_ready"] is False
    assert any(
        "pulse_slot_closed_at" in item for item in payload["readiness_reasons"]
    )
