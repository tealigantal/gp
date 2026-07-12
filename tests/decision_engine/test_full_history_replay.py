from __future__ import annotations

import json
import sqlite3

import pandas as pd

from gp_assistant.decision_engine.pipeline import _critical_candidate_reasons
from gp_assistant.evaluation_engine import historical_replay
from gp_assistant.evaluation_engine.historical_data import ReadOnlyHistoryStore
from gp_assistant.signal_engine.daily import build_signal_events_for_symbol


def _history_db(path):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE queries(id TEXT PRIMARY KEY, params TEXT, created_at TEXT, updated_at TEXT, last_fetch_at TEXT, last_item_time TEXT)"
    )
    connection.execute(
        "CREATE TABLE items(query_id TEXT, item_id TEXT, item_time TEXT, etag TEXT, payload TEXT, updated_at TEXT, PRIMARY KEY(query_id, item_id))"
    )
    connection.execute("CREATE INDEX idx_items_query_time ON items(query_id, item_time)")
    dates = pd.bdate_range("2025-01-02", periods=130)
    for offset, symbol in enumerate(("000001", "600000")):
        query_id = f"daily-{symbol}"
        connection.execute(
            "INSERT INTO queries VALUES(?,?,?,?,?,?)",
            (
                query_id,
                json.dumps({"kind": "daily", "symbol": symbol, "provider": "test"}),
                "2025-01-01",
                "2025-01-01",
                "2025-12-31",
                dates[-1].date().isoformat(),
            ),
        )
        for index, date in enumerate(dates):
            close = 10.0 + offset + index * 0.01
            payload = {
                "date": date.date().isoformat(),
                "open": close - 0.02,
                "high": close + 0.10,
                "low": close - 0.10,
                "close": close,
                "volume": 1000 + index,
                "amount": 10000 + index,
            }
            connection.execute(
                "INSERT INTO items VALUES(?,?,?,?,?,?)",
                (query_id, payload["date"], payload["date"], None, json.dumps(payload), payload["date"]),
            )
    connection.commit()
    connection.close()
    return dates


def test_read_only_history_store_reconstructs_as_of_data(tmp_path):
    path = tmp_path / "history.db"
    dates = _history_db(path)
    as_of = dates[119].date().isoformat()
    before = path.stat().st_size

    with ReadOnlyHistoryStore(path) as store:
        assert store.eligible_symbols(as_of, min_history=120) == ["000001", "600000"]
        frame, meta = store.daily_ohlcv("000001", as_of=as_of, min_len=120, prefer_cache_only=True)
        assert len(frame) == 120
        assert meta["source"] == "history_db_read_only"
        assert meta["network_attempted"] is False
        context = store.market_context(as_of, ["000001", "600000"])
        assert context["raw"]["breadth_count"] == 2
        full_context = store.market_context(as_of, None, min_history=120)
        assert full_context["raw"]["breadth_count"] == 2
        assert store.rank_universe(as_of, ["600000", "000001"], limit=1) == ["000001"]
        store.prepare_market_index([as_of], min_history=120, rank_limit=1)
        assert store.rank_universe(as_of, ["600000", "000001"], limit=1) == ["000001"]
        outcome = store.future_outcome(
            {
                "symbol": "000001",
                "trade_plan": {
                    "entry": {"low": float(frame["close"].iloc[-1]) - 0.2, "high": float(frame["close"].iloc[-1]) + 0.2},
                    "stop": {"price": float(frame["close"].iloc[-1]) - 1.0},
                    "take_profit": {"targets": [float(frame["close"].iloc[-1]) + 1.0]},
                },
            },
            as_of=as_of,
            friction_bps=30.0,
        )
        assert outcome["complete"] is True
        assert outcome["filled"] is True
        assert outcome["matured_at"] == dates[124].date().isoformat()
        unfilled = store.future_outcome(
            {
                "symbol": "000001",
                "trade_plan": {
                    "entry": {"price": 9999.0},
                    "stop": {"price": 9.0},
                    "take_profit": {"targets": [11.0]},
                },
            },
            as_of=as_of,
        )
        assert unfilled["complete"] is True
        assert unfilled["filled"] is False
        assert unfilled["net_return_3d"] is None

    assert path.stat().st_size == before


def test_precomputed_indicators_match_raw_signal_build(tmp_path):
    path = tmp_path / "history.db"
    dates = _history_db(path)
    as_of = dates[119].date().isoformat()
    with ReadOnlyHistoryStore(path) as store:
        precomputed, _ = store.daily_ohlcv("000001", as_of=as_of, min_len=120)
        raw = precomputed[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
        context = {"grade": "C", "market_regime": "C"}
        left = build_signal_events_for_symbol(symbol="000001", df=precomputed, as_of=as_of, market_context=context)
        right = build_signal_events_for_symbol(symbol="000001", df=raw, as_of=as_of, market_context=context)
        resolved = build_signal_events_for_symbol(
            symbol="000001",
            df=precomputed,
            as_of=as_of,
            market_context=context,
            historical_market_context_resolver=lambda day: {"grade": "A", "market_regime": "A", "as_of": day},
        )
        incremental = build_signal_events_for_symbol(
            symbol="000001",
            df=precomputed,
            as_of=as_of,
            market_context=context,
            historical_event_mode="newly_matured",
        )

    assert left.current_event is not None
    assert right.current_event is not None
    assert left.current_event.signal_type == right.current_event.signal_type
    assert left.current_event.feature_vector == right.current_event.feature_vector
    assert resolved.current_event is not None
    assert resolved.current_event.market_context["market_regime"] == "C"
    assert resolved.historical_events
    assert all(event.market_context["market_regime"] == "A" for event in resolved.historical_events)
    assert len(incremental.historical_events) == 1
    assert incremental.historical_events[0].event_id == left.historical_events[-1].event_id


def test_critical_candidate_data_is_hard_blocked():
    candidate = {
        "symbol": "000001",
        "last_date": "2026-01-05",
        "data_status": {
            "ok": True,
            "rows": 119,
            "as_of": "2026-01-05",
            "daily_meta": {"len": 119, "freshness_state": "stale", "strict_blocked": True},
        },
        "risk": {"entry": {}, "stop": {}},
        "ranking": {"ranking_score": float("nan")},
    }

    reasons = _critical_candidate_reasons(candidate, as_of="2026-01-05")

    assert "daily_history_lt_120" in reasons
    assert "daily_cache_not_current" in reasons
    assert "entry_plan_missing" in reasons
    assert "stop_plan_missing" in reasons
    assert "ranking_score_non_finite" in reasons


def test_policy_updates_wait_until_outcome_matures(monkeypatch, tmp_path):
    seen_update_counts = []

    monkeypatch.setenv("GP_MARKET_MEMORY_DIR", str(tmp_path / "events"))
    monkeypatch.setattr(historical_replay, "load_policy_state", lambda: {"update_count": 0})
    monkeypatch.setattr(historical_replay, "save_policy_state", lambda state: None)
    monkeypatch.setattr(
        historical_replay,
        "update_policy_state_from_outcomes",
        lambda state, records: {**state, "update_count": int(state.get("update_count", 0)) + len(records)},
    )
    monkeypatch.setattr(
        historical_replay,
        "load_replay_universe",
        lambda day, max_symbols=30: {"day": day, "symbols": ["000001"], "source": "test"},
    )
    monkeypatch.setattr(
        historical_replay,
        "_run_legacy_baseline",
        lambda **kwargs: {"decision": "no_trade", "picks": [], "candidate_pool": []},
    )

    def fake_selection(**kwargs):
        seen_update_counts.append(int((kwargs.get("policy_state") or {}).get("update_count", 0)))
        return {"decision": "recommend", "tradeable": True, "picks": [{"symbol": "000001"}], "candidate_pool": []}

    def fake_evaluate(payload, *, as_of, pipeline, topn=3, **kwargs):
        if pipeline != "new":
            return {"decision": "no_trade", "evaluated_picks": [], "evaluated_rejected": [], "evaluated_alternatives": []}
        return {
            "decision": "recommend",
            "evaluated_picks": [
                {
                    "pick": {"symbol": "000001"},
                    "outcome": {"complete": True, "matured_at": "2026-01-08", "return_3d": 0.01, "success": True},
                }
            ],
            "evaluated_rejected": [],
            "evaluated_alternatives": [],
        }

    monkeypatch.setattr(historical_replay, "run_market_memory_selection", fake_selection)
    monkeypatch.setattr(historical_replay, "_evaluate_payload", fake_evaluate)

    report = historical_replay.run_historical_replay_ab(
        ["2026-01-05", "2026-01-06", "2026-01-08", "2026-01-09"],
        update_policy_state=True,
    )

    assert seen_update_counts[:2] == [0, 0]
    assert seen_update_counts[2] == 2
    assert seen_update_counts[3] == 3
    assert report["pending_policy_update_batches"] == 1
