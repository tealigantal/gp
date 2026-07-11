from __future__ import annotations

import json

import pytest

from gp_assistant.book import repo
from gp_assistant.book.readonly import build_daily_plan_artifact, tracked_universe_from_daybook
from gp_assistant.contracts.objects import AdvicePick, CurrentSlotPointer, DayBook
from gp_assistant.runtime.producer import producer_metadata


def _daybook() -> DayBook:
    return DayBook(
        trading_day="20260710",
        generated_at="2026-07-10T16:00:00+08:00",
        tradeable=True,
        picks=[
            AdvicePick(
                symbol="600519",
                rank=1,
                entry_plan={"low": 1400.0, "high": 1420.0},
                stop_plan={"price": 1370.0},
                take_profit_plan={"targets": [1500.0]},
                scores={"final": 0.7},
            )
        ],
        source_meta={"decision": "recommend", "selection_policy": "adaptive_policy_single_path"},
        producer=producer_metadata(),
    )


def test_current_pointer_commits_immutable_versioned_book(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    daybook = _daybook()
    artifact = build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked_universe_from_daybook(daybook),
        market_phase="NON_TRADING",
        trade_day="20260710",
        portfolio_snapshot={},
    )
    repo.publish_current_bundle(daybook, artifact)

    raw = daybook.model_dump()
    raw["picks"] = []
    repo.daybook_path(daybook.trading_day).write_text(json.dumps(raw), encoding="utf-8")

    current = repo.load_current_book()
    assert current is not None
    assert [entry.symbol for entry in current.board] == ["600519"]
    assert current.publish_allowed is False


def test_incompatible_pointer_is_rejected_without_replacing_current(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    daybook = _daybook()
    artifact = build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked_universe_from_daybook(daybook),
        market_phase="NON_TRADING",
        trade_day="20260710",
        portfolio_snapshot={},
    )
    repo.publish_current_bundle(daybook, artifact)
    before = repo.current_pointer_path().read_bytes()

    with pytest.raises(RuntimeError, match="incompatible_runtime_producer"):
        repo.save_current_pointer(
            CurrentSlotPointer(
                artifact_id="legacy",
                trade_day="20260710",
                updated_at="2026-07-11T00:00:00+08:00",
                producer={"revision": "old", "schema_version": "v1", "selection_policy": "risk_committee"},
            )
        )

    assert repo.current_pointer_path().read_bytes() == before


def test_pointer_is_not_changed_when_bundle_validation_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    daybook = _daybook()
    artifact = build_daily_plan_artifact(
        daybook=daybook,
        tracked_universe=tracked_universe_from_daybook(daybook),
        market_phase="NON_TRADING",
        trade_day="20260710",
        portfolio_snapshot={},
    )
    repo.publish_current_bundle(daybook, artifact)
    before = repo.current_pointer_path().read_bytes()
    broken = artifact.model_copy(deep=True)
    broken.artifact_id = "broken"
    broken.daybook_effective_day = "20260709"

    with pytest.raises(RuntimeError, match="trade_day_mismatch"):
        repo.publish_current_bundle(daybook, broken)

    assert repo.current_pointer_path().read_bytes() == before
