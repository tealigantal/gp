from __future__ import annotations

import pandas as pd
from pathlib import Path

from src.backtest.tournament import _evaluate_period, Candidate
from src.backtest.engine import CostModel
from src.providers.local_store import LocalParquetStore


def test_tournament_selection_no_lookahead(monkeypatch, tmp_path: Path):
    root = Path.cwd()
    # Patch YAML loader to always return baseline type
    from src.backtest import experiment as exp_mod
    monkeypatch.setattr(exp_mod, "_load_yaml", lambda p: {"type": "baseline", "name": Path(p).stem})

    # Prepare synthetic min5 and daily via monkeypatched store methods
    # Universe has one symbol
    sym = "000001.SZ"
    # Build bars for two days: 20250106 (train), 20250107 (oos)
    bars = {
        (sym, "20250106"): pd.DataFrame(
            [
                {"ts_code": sym, "trade_time": "20250106 09:35:00", "open": 10.00, "high": 10.00, "low": 10.00, "close": 10.00, "vol": 100, "amount": 1000},
                {"ts_code": sym, "trade_time": "20250106 09:40:00", "open": 10.10, "high": 10.20, "low": 10.00, "close": 10.15, "vol": 100, "amount": 1010},  # exec for 09:35
                {"ts_code": sym, "trade_time": "20250106 09:50:00", "open": 10.10, "high": 10.10, "low": 10.10, "close": 10.10, "vol": 100, "amount": 1010},
                {"ts_code": sym, "trade_time": "20250106 09:55:00", "open": 10.15, "high": 10.20, "low": 10.10, "close": 10.18, "vol": 100, "amount": 1015},  # exec for 09:50
            ]
        ),
        (sym, "20250107"): pd.DataFrame(
            [
                {"ts_code": sym, "trade_time": "20250107 09:35:00", "open": 10.18, "high": 10.18, "low": 10.18, "close": 10.18, "vol": 100, "amount": 1018},
                {"ts_code": sym, "trade_time": "20250107 09:40:00", "open": 10.00, "high": 10.00, "low": 10.00, "close": 10.00, "vol": 100, "amount": 1000},  # early entry worse
                {"ts_code": sym, "trade_time": "20250107 09:50:00", "open": 10.00, "high": 10.00, "low": 10.00, "close": 10.00, "vol": 100, "amount": 1000},
                {"ts_code": sym, "trade_time": "20250107 09:55:00", "open": 9.80, "high": 9.90, "low": 9.80, "close": 9.90, "vol": 100, "amount": 980},  # late entry worse next bar open
            ]
        ),
    }
    daily = pd.DataFrame([
        {"ts_code": sym, "trade_date": "20250105", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "vol": 100, "amount": 1000},
        {"ts_code": sym, "trade_date": "20250106", "open": 10.0, "high": 10.2, "low": 10.0, "close": 10.18, "vol": 200, "amount": 2000},
        {"ts_code": sym, "trade_date": "20250107", "open": 10.18, "high": 10.2, "low": 9.8, "close": 9.90, "vol": 200, "amount": 1900},
    ])

    # Monitor to ensure no reads beyond allowed end date during selection
    allowed_end = "20250106"

    def fake_read_min5(self, ts_code: str, date: str):
        # assert not reading beyond allowed_end during training selection
        assert date <= allowed_end, f"read_min5 leaked future date {date} > {allowed_end}"
        return bars.get((ts_code, date), pd.DataFrame())

    def fake_read_daily(self, ts_code: str, start: str | None = None, end: str | None = None):
        df = daily.copy()
        if start:
            df = df[df["trade_date"] >= start]
        if end:
            assert end <= allowed_end, f"read_daily leaked future end {end} > {allowed_end}"
            df = df[df["trade_date"] <= end]
        return df

    monkeypatch.setattr(LocalParquetStore, "read_min5", fake_read_min5)
    monkeypatch.setattr(LocalParquetStore, "read_daily", fake_read_daily)

    # Build candidates with different entry times
    c1 = Candidate(name="late", params={"entry_time": "09:50:00", "topk": 1, "lot_shares": 100}, file=Path("late.yaml"))
    c2 = Candidate(name="early", params={"entry_time": "09:35:00", "topk": 1, "lot_shares": 100}, file=Path("early.yaml"))
    candidates = [c1, c2]

    # Training period (up to t=20250106)
    train_dates = ["20250106"]
    universe_by_date = {"20250106": [sym], "20250107": [sym]}
    basics = pd.DataFrame([{"ts_code": sym, "exchange": "SZ", "is_st": False}])
    cost = CostModel(min_commission=0, slippage_bps=0)

    # Evaluate realistic (train window only)
    sel_real = _evaluate_period(candidates, train_dates, universe_by_date, basics, cost, root)
    # Oracle on OOS date (future)
    allowed_end = "20250107"  # allow reading up to oos end in oracle test
    sel_oracle = _evaluate_period(candidates, ["20250107"], universe_by_date, basics, cost, root)

    # pick champions by Sharpe
    def pick(m):
        return max(m.items(), key=lambda kv: (kv[1].get("Sharpe", 0.0), kv[1].get("expectancy", 0.0)))[0]

    champ_real = pick(sel_real)
    champ_oracle = pick(sel_oracle)
    assert champ_real != champ_oracle, "realistic and oracle champions should differ on constructed data"

