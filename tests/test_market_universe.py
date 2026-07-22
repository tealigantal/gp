from __future__ import annotations

import json

import pandas as pd

from gp_assistant.evidence.market_universe import (
    UniverseThresholds,
    build_market_universe_snapshot,
    finalize_market_universe_snapshot,
    load_accepted_market_universe,
    normalize_exchange_master,
)


TARGET = "2026-07-22"


def _bars(*, close: float = 10.0, amount: float = 600_000_000.0, rows: int = 130, last: str = TARGET):
    dates = pd.bdate_range(end=last, periods=rows)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0,
            "amount": amount,
        }
    )


def _master():
    return [
        (
            "sse:test",
            pd.DataFrame(
                {
                    "证券代码": ["600001", "600002", "688001"],
                    "证券简称": ["上证一", "ST上证二", "科创一"],
                    "上市日期": ["2020-01-01", "2020-01-01", "2020-01-01"],
                }
            ),
        ),
        (
            "szse:test",
            pd.DataFrame(
                {
                    "A股代码": ["000001", "001001", "300001"],
                    "A股简称": ["深证一", "深证二", "创业一"],
                    "A股上市日期": ["2020-01-01", "2026-07-01", "2020-01-01"],
                }
            ),
        ),
    ]


def _thresholds(**overrides):
    values = {
        "minimum_mainboard_count": 4,
        "minimum_eligible_count": 2,
        "scoring_pool_limit": 2,
        "minimum_scored_count": 2,
    }
    values.update(overrides)
    return UniverseThresholds(**values)


def test_exchange_master_normalization_keeps_only_mainboard():
    rows, meta = normalize_exchange_master(_master())

    assert [row["symbol"] for row in rows] == ["000001", "001001", "600001", "600002"]
    assert meta["mainboard_count"] == 4


def test_full_market_filters_and_top_pool_are_deterministic():
    daily = {
        "000001": (_bars(amount=800_000_000.0), {"source": "test", "strict_blocked": False}),
        "001001": (_bars(amount=900_000_000.0), {"source": "test", "strict_blocked": False}),
        "600001": (_bars(amount=800_000_000.0), {"source": "test", "strict_blocked": False}),
        "600002": (_bars(amount=1_000_000_000.0), {"source": "test", "strict_blocked": False}),
    }
    draft = build_market_universe_snapshot(
        TARGET,
        thresholds=_thresholds(),
        master_frames=_master(),
        daily_loader=lambda symbols, as_of: {symbol: daily[symbol] for symbol in symbols},
        previous_accepted_count=4,
    )

    assert draft["complete"] is True
    assert draft["counts"] == {
        "mainboard_input_count": 4,
        "metadata_complete_count": 4,
        "daily_ready_count": 4,
        "eligible_count": 2,
        "scoring_pool_count": 2,
        "scored_count": 0,
        "selected_count": 0,
    }
    # ST and a newly listed symbol are excluded. Equal liquidity is resolved by code.
    assert [item["symbol"] for item in draft["scoring_pool"]] == ["000001", "600001"]
    assert draft["exclusions"]["st_or_delisting"] == 1
    assert draft["exclusions"]["listing_age_lt_60"] == 1


def test_coverage_and_scoring_thresholds_fail_closed():
    daily = {
        "000001": (_bars(), {"source": "test", "strict_blocked": False}),
        "001001": (_bars(), {"source": "test", "strict_blocked": False}),
        "600001": (_bars(last="2026-07-21"), {"source": "test", "strict_blocked": True}),
        "600002": (_bars(last="2026-07-21"), {"source": "test", "strict_blocked": True}),
    }
    draft = build_market_universe_snapshot(
        TARGET,
        thresholds=_thresholds(daily_coverage_ratio=0.95),
        master_frames=_master(),
        daily_loader=lambda symbols, as_of: {symbol: daily[symbol] for symbol in symbols},
        previous_accepted_count=5,
    )
    finalized = finalize_market_universe_snapshot(draft, scored_count=1, selected_count=0, persist=False)

    assert finalized["complete"] is False
    assert finalized["blocking_reason"] == "candidate_universe_incomplete"
    assert "mainboard_count_below_previous_ratio" in finalized["blocking_reasons"]
    assert "target_daily_coverage_below_threshold" in finalized["blocking_reasons"]
    assert "scored_count_below_minimum" in finalized["blocking_reasons"]
    assert finalized["fallback_used"] is False


def test_market_universe_storage_is_content_addressed_and_immutable(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_STORE_DIR", str(tmp_path / "store"))
    daily = {
        symbol: (_bars(), {"source": "test", "strict_blocked": False})
        for symbol in ("000001", "001001", "600001", "600002")
    }
    draft = build_market_universe_snapshot(
        TARGET,
        thresholds=_thresholds(minimum_eligible_count=1),
        master_frames=_master(),
        daily_loader=lambda symbols, as_of: {symbol: daily[symbol] for symbol in symbols},
        previous_accepted_count=4,
    )
    first = finalize_market_universe_snapshot(draft, scored_count=2, selected_count=1)
    second = finalize_market_universe_snapshot(draft, scored_count=2, selected_count=1)

    assert first == second
    path = tmp_path / "store" / "universe" / "snapshots" / TARGET / f"{first['universe_id']}.json"
    pointer = tmp_path / "store" / "universe" / "snapshots" / "current.json"
    assert json.loads(path.read_text(encoding="utf-8")) == first
    assert json.loads(pointer.read_text(encoding="utf-8"))["universe_id"] == first["universe_id"]
    assert load_accepted_market_universe(TARGET) == first
