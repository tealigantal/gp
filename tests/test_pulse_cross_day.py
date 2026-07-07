import pandas as pd
from gp_assistant.book import pulse5m
from gp_assistant.book.pulse5m import apply_pulse
from gp_assistant.contracts.objects import MarketBook, DayBook, AdvicePick, SymbolPulse, TrackedUniverse
from gp_assistant.evidence import market_service


def _mk_book_with_picks(day: str = '20240319') -> MarketBook:
    db = DayBook(trading_day=day, generated_at=f'{day}T16:10:00', regime={}, tradeable=True, picks=[
        AdvicePick(symbol='600519', rank=1),
        AdvicePick(symbol='000001', rank=2),
    ])
    return MarketBook(trading_day=day, book_version='v1', updated_at=f'{day}T16:10:00', regime={}, daybook=db)


def test_no_carry_over_yesterday_pulse_when_no_closed_bar():
    book = _mk_book_with_picks('20240319')
    # seed yesterday pulse to simulate existing state
    book.symbol_states['600519'] = SymbolPulse(symbol='600519', last_bar_at='2024-03-19T14:55:00', pulse_score=0.1,
                                               momentum_state='up', stretch_state='normal', liquidity_state='good',
                                               execution_state='observe', invalidated=False, trade_day='20240319', slot_at='2024-03-19 14:55:00')
    # next day 09:32 -> no closed bar yet
    out = apply_pulse(book, ['600519'], target_trade_day='20240320', target_slot_at=None)
    assert out.symbol_states['600519'].is_stale is True
    assert out.symbol_states['600519'].stale_reason == 'no_closed_bar_yet'


def test_lunch_break_slot_pulse_package_runs_on_1130_closed_bar(monkeypatch):
    daybook = DayBook(
        trading_day="20260707",
        generated_at="2026-07-07T09:00:00+08:00",
        tradeable=True,
        picks=[
            AdvicePick(
                symbol="600519",
                rank=1,
                name="贵州茅台",
                scores={"final": 0.82},
                entry_plan={"mid": 10.18, "high": 10.30},
                stop_plan={"price": 9.85},
                take_profit_plan={"targets": [10.8]},
            )
        ],
    )
    bars = pd.DataFrame(
        [
            {"trade_time": "2026-07-07 11:20:00", "open": 10.00, "high": 10.10, "low": 9.95, "close": 10.05, "vol": 100, "amount": 1005},
            {"trade_time": "2026-07-07 11:25:00", "open": 10.05, "high": 10.20, "low": 10.00, "close": 10.15, "vol": 120, "amount": 1218},
            {"trade_time": "2026-07-07 11:30:00", "open": 10.15, "high": 10.35, "low": 10.10, "close": 10.30, "vol": 180, "amount": 1854},
        ]
    )
    benchmark = pd.DataFrame(
        [
            {"trade_time": "2026-07-07 11:20:00", "open": 10.00, "high": 10.02, "low": 9.98, "close": 10.01, "vol": 100, "amount": 1001},
            {"trade_time": "2026-07-07 11:25:00", "open": 10.01, "high": 10.03, "low": 9.99, "close": 10.02, "vol": 100, "amount": 1002},
            {"trade_time": "2026-07-07 11:30:00", "open": 10.02, "high": 10.04, "low": 10.00, "close": 10.03, "vol": 100, "amount": 1003},
        ]
    )
    monkeypatch.setattr(
        pulse5m,
        "fetch_intraday_bundle",
        lambda **_: {
            "bars": {"600519": bars},
            "benchmark": benchmark,
            "snapshot": pd.DataFrame([{"symbol": "600519", "pct_chg": 1.5, "ts": "2026-07-07 11:30:00"}]),
            "provider": "akshare",
            "errors": [],
            "snapshot_age_sec": 1,
            "symbols_expected": 1,
            "symbols_received": 1,
            "benchmark_received": True,
        },
    )
    monkeypatch.setattr(pulse5m, "load_slot_volume_baselines", lambda trade_day, symbols: {"600519": {"11:30": 100.0}})

    pkg = pulse5m.compute_slot_pulse_package(
        daybook=daybook,
        tracked_universe=TrackedUniverse(reco=["600519"], total=["600519"]),
        trade_day="20260707",
        slot_at="2026-07-07 11:30:00",
        benchmark_symbol="000300",
    )

    assert pkg["bundle"]["symbols_received"] == 1
    assert pkg["pulses"]["600519"].slot_at == "2026-07-07 11:30:00"
    assert pkg["pulses"]["600519"].feature_snapshot["slot_at"] == "2026-07-07 11:30:00"


def test_slot_pulse_package_reads_minute_cache_without_live_fetch(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_DATA_DIR", str(tmp_path / "data"))
    daybook = DayBook(
        trading_day="20260707",
        generated_at="2026-07-07T09:00:00+08:00",
        tradeable=True,
        picks=[AdvicePick(symbol="600519", rank=1, name="贵州茅台", scores={"final": 0.82})],
    )
    bars = pd.DataFrame(
        [
            {"trade_time": "2026-07-07 13:50:00", "open": 10.00, "high": 10.10, "low": 9.95, "close": 10.05, "vol": 100, "amount": 1005},
            {"trade_time": "2026-07-07 13:55:00", "open": 10.05, "high": 10.20, "low": 10.00, "close": 10.15, "vol": 120, "amount": 1218},
            {"trade_time": "2026-07-07 14:00:00", "open": 10.15, "high": 10.35, "low": 10.10, "close": 10.30, "vol": 180, "amount": 1854},
        ]
    )
    benchmark = pd.DataFrame(
        [
            {"trade_time": "2026-07-07 13:50:00", "open": 10.00, "high": 10.02, "low": 9.98, "close": 10.01, "vol": 100, "amount": 1001},
            {"trade_time": "2026-07-07 13:55:00", "open": 10.01, "high": 10.03, "low": 9.99, "close": 10.02, "vol": 100, "amount": 1002},
            {"trade_time": "2026-07-07 14:00:00", "open": 10.02, "high": 10.04, "low": 10.00, "close": 10.03, "vol": 100, "amount": 1003},
        ]
    )
    market_service._write_cached_day("600519", "20260707", bars, kind="stock")
    market_service._write_cached_day("000300", "20260707", benchmark, kind="index")
    monkeypatch.setattr(
        market_service,
        "_provider_minute_bars",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("artifact generation must not live-fetch stock bars")),
    )
    monkeypatch.setattr(
        market_service,
        "_provider_index_bars",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("artifact generation must not live-fetch benchmark bars")),
    )
    monkeypatch.setattr(pulse5m, "load_slot_volume_baselines", lambda trade_day, symbols: {"600519": {"14:00": 100.0}})

    pkg = pulse5m.compute_slot_pulse_package(
        daybook=daybook,
        tracked_universe=TrackedUniverse(reco=["600519"], total=["600519"]),
        trade_day="20260707",
        slot_at="2026-07-07 14:00:00",
        benchmark_symbol="000300",
    )

    pulse = pkg["pulses"]["600519"]
    assert pkg["bundle"]["model_usable"] is True
    assert pkg["bundle"]["effective_slot_at"] == "2026-07-07 14:00:00"
    assert pulse.feature_snapshot["target_slot_at"] == "2026-07-07 14:00:00"
    assert pulse.feature_snapshot["effective_slot_at"] == "2026-07-07 14:00:00"
    assert pulse.feature_snapshot["freshness_state"] == "fresh"
