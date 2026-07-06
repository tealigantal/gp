from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from gp_assistant.selection_engine.hot_boards import score_symbols_for_hot_boards
from gp_assistant.selection_engine.market_context import annotate_tail_confirmation, build_market_context
from gp_assistant.selection_engine.strategy_weights import strategy_weight_from_samples
from gp_assistant.selection_engine.tail_risk import effective_reward_risk
from gp_assistant.strategy.strategies import s06_breakout_pullback as s06
from gp_assistant.strategy.strategies import s12_avwap as s12


def _base_ohlcv(n: int = 80, close: float = 10.0) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [close] * n,
            "high": [close * 1.01] * n,
            "low": [close * 0.99] * n,
            "close": [close] * n,
            "volume": [1_000_000.0] * n,
            "amount": [close * 1_000_000.0] * n,
        }
    )


def test_s6_requires_recovered_support_after_breakout_pullback():
    df = _base_ohlcv(50, 10.0)
    df.loc[30, ["open", "high", "low", "close"]] = [10.2, 11.6, 10.1, 11.4]
    df.loc[32, ["open", "high", "low", "close"]] = [10.25, 10.55, 10.20, 10.38]
    ok = s06.detect_setups(df)
    assert ok
    assert ok[-1].idx == 32

    broken = df.copy()
    broken.loc[32, ["open", "high", "low", "close"]] = [10.6, 10.7, 9.7, 9.9]
    assert not s06.detect_setups(broken)


def test_s12_avwap_is_recently_anchored_and_rejects_large_deviation():
    df = _base_ohlcv(90, 100.0)
    df.loc[:20, ["open", "high", "low", "close"]] = [100.0, 101.0, 99.0, 100.0]
    df.loc[:20, "volume"] = 10_000_000.0
    df.loc[60:89, ["open", "high", "low", "close"]] = [52.0, 53.0, 50.0, 52.0]
    df.loc[89, ["open", "high", "low", "close"]] = [51.5, 55.0, 51.0, 54.0]

    avwap = s12._avwap(df)  # noqa: SLF001 - strategy helper is intentionally unit-tested.
    assert float(avwap.iloc[-1]) < 60.0
    assert s12.detect_setups(df)

    extended = df.copy()
    extended.loc[89, ["open", "high", "low", "close"]] = [51.5, 70.0, 51.0, 70.0]
    assert not s12.detect_setups(extended)


def test_effective_reward_risk_caps_extreme_fake_rr():
    rr = effective_reward_risk(price=100.0, support=99.99, target=110.0, atr=2.0)
    assert rr["raw"] > 500
    assert rr["effective"] == 5.0
    assert rr["capped"] is True

    hard_cap = effective_reward_risk(price=100.0, support=99.0, target=130.0, atr=1.0)
    assert hard_cap["effective"] == 8.0


def test_tail_context_blocks_price_below_support_without_daily_mutation():
    snapshot = pd.DataFrame(
        [
            {"code": "600519", "price": 98.0, "pct_chg": -1.2, "high": 102.0, "low": 97.5, "open": 101.0, "prev_close": 100.0, "amount": 1e9}
        ]
    )
    state = SimpleNamespace(market_phase="INTRADAY_PM")
    context = build_market_context(snapshot, {"source": "test"}, market_state=state)
    assert context["used_for_tail_confirmation"] is True

    items = [
        {
            "symbol": "600519",
            "trade_plan": {
                "bands": {"S1": 100.0},
                "stop": {"price": 100.0},
            },
        }
    ]
    annotate_tail_confirmation(items, context, env={"grade": "B"})
    assert items[0]["tail_entry_blocked"] is True
    assert items[0]["breakdown_penalty"] < -1.0
    assert "tail_below_stop_or_support" in items[0]["midday_adjustment_reason_codes"]


def test_hot_board_score_does_not_override_breakdown_policy():
    snapshot = {
        "status": "available",
        "memberships": {
            "600519": [{"type": "concept", "name": "strong", "score": 0.95, "pct_chg": 6.0}]
        },
    }
    score = score_symbols_for_hot_boards(["600519"], snapshot)["600519"]
    assert score["score"] == 0.95
    assert score["reason_codes"] == ["hot_board_match"]


def test_strategy_weight_formula_matches_plan_bounds():
    assert strategy_weight_from_samples(0.5, 0.0) == 1.0
    assert strategy_weight_from_samples(0.8, 0.05) == 1.25
    assert strategy_weight_from_samples(0.1, -0.10) == 0.65
