from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from gp_assistant.evidence import market_service


def _cfg(**overrides):
    base = {
        "intraday_benchmark_symbol": "000300",
        "intraday_model_max_stale_sec": 600,
        "intraday_min5_refresh_sec": 1,
        "intraday_fetch_budget_sec": 110,
        "intraday_symbol_cooldown_sec": 90,
        "intraday_core_first": True,
        "intraday_fetch_workers": 2,
        "intraday_fetch_timeout_sec": 5,
        "intraday_fetch_retry_missing": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _bars(times: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"trade_time": ts, "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1010}
            for ts in times
        ]
    )


def _isolate_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("GP_DATA_DIR", str(tmp_path / "data"))


def test_fetch_minute_bars_timeout_does_not_wait_for_unfinished_futures(monkeypatch):
    class FakeFuture:
        def __init__(self, symbol: str):
            self.symbol = symbol
            self.cancelled = False

        def done(self) -> bool:
            return False

        def cancel(self) -> bool:
            self.cancelled = True
            return True

    class FakeExecutor:
        last: "FakeExecutor | None" = None

        def __init__(self, max_workers: int):
            self.max_workers = max_workers
            self.futures: list[FakeFuture] = []
            self.shutdown_args: dict[str, object] = {}
            FakeExecutor.last = self

        def submit(self, fn, symbol: str):  # noqa: ANN001
            future = FakeFuture(symbol)
            self.futures.append(future)
            return future

        def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
            self.shutdown_args = {"wait": wait, "cancel_futures": cancel_futures}

    def _timeout(*args, **kwargs):  # noqa: ANN001
        raise market_service.FuturesTimeoutError("2 (of 2) futures unfinished")

    monkeypatch.setattr(market_service, "load_config", lambda: SimpleNamespace(intraday_fetch_workers=2, intraday_fetch_timeout_sec=5))
    monkeypatch.setattr(market_service, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(market_service, "as_completed", _timeout)

    out = market_service.fetch_minute_bars_5m(["600519", "000001"], "20260707", slot_at="2026-07-07 11:30:00")

    assert out == {}
    assert FakeExecutor.last is not None
    assert FakeExecutor.last.shutdown_args == {"wait": False, "cancel_futures": True}
    assert [future.cancelled for future in FakeExecutor.last.futures] == [True, True]


def test_fetch_intraday_bundle_degrades_when_cache_is_incomplete(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg())
    monkeypatch.setattr(
        market_service,
        "_provider_minute_bars",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("bundle must not live-fetch stock bars")),
    )
    monkeypatch.setattr(
        market_service,
        "_provider_index_bars",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("bundle must not live-fetch benchmark bars")),
    )

    bundle = market_service.fetch_intraday_bundle(
        trading_day="20260707",
        slot_at="2026-07-07 13:10:00",
        symbols=["600519", "000001"],
        core_symbols=["600519"],
    )

    assert bundle["symbols_expected"] == 2
    assert bundle["symbols_received"] == 0
    assert bundle["benchmark_received"] is False
    assert bundle["model_usable"] is False
    assert bundle["freshness_state"] == "degraded"
    assert "core_symbols_missing:600519" in bundle["errors"]
    assert "benchmark_missing:000300" in bundle["errors"]


def test_fetch_intraday_bundle_reads_cache_and_derives_snapshot(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg())
    market_service._write_cached_day("600519", "20260707", _bars(["2026-07-07 13:55:00", "2026-07-07 14:00:00"]), kind="stock")
    market_service._write_cached_day("000300", "20260707", _bars(["2026-07-07 13:55:00", "2026-07-07 14:00:00"]), kind="index")
    monkeypatch.setattr(
        market_service,
        "_provider_minute_bars",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("bundle must not live-fetch stock bars")),
    )

    bundle = market_service.fetch_intraday_bundle(
        trading_day="20260707",
        slot_at="2026-07-07 14:00:00",
        symbols=["600519"],
        core_symbols=["600519"],
    )

    assert bundle["symbols_received"] == 1
    assert bundle["benchmark_received"] is True
    assert bundle["model_usable"] is True
    assert bundle["freshness_state"] == "fresh"
    assert bundle["effective_slot_at"] == "2026-07-07 14:00:00"
    assert bundle["snapshot_age_sec"] == 0.0
    assert bundle["errors"] == []
    assert bundle["snapshot"]["symbol"].tolist() == ["600519"]
    assert float(bundle["snapshot"]["pct_chg"].iloc[0]) > 0


def test_fetch_intraday_bundle_allows_usable_stale_cache(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg(intraday_model_max_stale_sec=600))
    market_service._write_cached_day("600519", "20260707", _bars(["2026-07-07 13:55:00"]), kind="stock")
    market_service._write_cached_day("000300", "20260707", _bars(["2026-07-07 13:55:00"]), kind="index")

    bundle = market_service.fetch_intraday_bundle(
        trading_day="20260707",
        slot_at="2026-07-07 14:05:00",
        symbols=["600519"],
        core_symbols=["600519"],
    )

    assert bundle["model_usable"] is True
    assert bundle["freshness_state"] == "usable_stale"
    assert bundle["data_age_sec"] == 600.0
    assert bundle["usable_stale_symbols"] == ["600519"]
    assert bundle["errors"] == []


def test_fetch_intraday_bundle_keeps_per_symbol_freshness_after_effective_slot(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg(intraday_model_max_stale_sec=600))
    market_service._write_cached_day("600519", "20260707", _bars(["2026-07-07 13:55:00", "2026-07-07 14:00:00"]), kind="stock")
    market_service._write_cached_day("603019", "20260707", _bars(["2026-07-07 13:55:00"]), kind="stock")
    market_service._write_cached_day("000300", "20260707", _bars(["2026-07-07 14:00:00"]), kind="index")

    bundle = market_service.fetch_intraday_bundle(
        trading_day="20260707",
        slot_at="2026-07-07 14:05:00",
        symbols=["600519", "603019"],
        core_symbols=["600519"],
    )

    assert bundle["model_usable"] is True
    assert bundle["freshness_state"] == "fresh"
    assert bundle["fresh_symbols"] == ["600519"]
    assert bundle["usable_stale_symbols"] == ["603019"]
    assert bundle["symbol_statuses"]["603019"]["freshness_state"] == "usable_stale"
    assert bundle["symbol_statuses"]["603019"]["effective_slot_at"] == "2026-07-07 13:55:00"
    assert bundle["symbol_statuses"]["603019"]["data_age_sec"] == 600.0


def test_fetch_intraday_bundle_degrades_when_cache_is_too_old(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg(intraday_model_max_stale_sec=600))
    market_service._write_cached_day("600519", "20260707", _bars(["2026-07-07 13:50:00"]), kind="stock")
    market_service._write_cached_day("000300", "20260707", _bars(["2026-07-07 13:50:00"]), kind="index")

    bundle = market_service.fetch_intraday_bundle(
        trading_day="20260707",
        slot_at="2026-07-07 14:05:00",
        symbols=["600519"],
        core_symbols=["600519"],
    )

    assert bundle["model_usable"] is False
    assert bundle["freshness_state"] == "degraded"
    assert bundle["symbols_received"] == 0
    assert "core_symbols_missing:600519" in bundle["errors"]


def test_fetch_minute_bars_retries_missing_symbols_after_batch_timeout(monkeypatch):
    bars = pd.DataFrame(
        [
            {"trade_time": "2026-07-07 14:00:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "vol": 100, "amount": 1010},
        ]
    )

    class FakeFuture:
        def __init__(self, symbol: str, *, done: bool):
            self.symbol = symbol
            self._done = done
            self.cancelled = False

        def done(self) -> bool:
            return self._done

        def cancel(self) -> bool:
            self.cancelled = True
            return True

        def result(self, timeout: int = 0):  # noqa: ARG002
            return self.symbol, bars

    class FakeExecutor:
        last: "FakeExecutor | None" = None

        def __init__(self, max_workers: int):
            self.max_workers = max_workers
            self.futures: list[FakeFuture] = []
            self.shutdown_args: dict[str, object] = {}
            FakeExecutor.last = self

        def submit(self, fn, symbol: str):  # noqa: ANN001, ARG002
            future = FakeFuture(symbol, done=(symbol == "600519"))
            self.futures.append(future)
            return future

        def shutdown(self, *, wait: bool = True, cancel_futures: bool = False) -> None:
            self.shutdown_args = {"wait": wait, "cancel_futures": cancel_futures}

    def _as_completed(futures, timeout):  # noqa: ANN001
        for future in futures:
            if future.done():
                yield future
        raise market_service.FuturesTimeoutError("1 (of 2) futures unfinished")

    calls: list[str] = []

    def _fetch(symbol, trading_day, start_date, end_date, *, kind):  # noqa: ANN001, ARG001
        calls.append(symbol)
        return bars

    monkeypatch.setattr(
        market_service,
        "load_config",
        lambda: SimpleNamespace(
            intraday_fetch_workers=2,
            intraday_fetch_timeout_sec=5,
            intraday_fetch_retry_missing=True,
        ),
    )
    monkeypatch.setattr(market_service, "ThreadPoolExecutor", FakeExecutor)
    monkeypatch.setattr(market_service, "as_completed", _as_completed)
    monkeypatch.setattr(market_service, "_fetch_cached_or_live", _fetch)

    out = market_service.fetch_minute_bars_5m(["600519", "603019"], "20260707", slot_at="2026-07-07 14:00:00")

    assert set(out) == {"600519", "603019"}
    assert calls == ["603019"]
    assert FakeExecutor.last is not None
    assert FakeExecutor.last.shutdown_args == {"wait": False, "cancel_futures": True}


def test_refresh_intraday_cache_fetches_benchmark_then_core_first(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg(intraday_symbol_cooldown_sec=0))
    calls: list[tuple[str, str]] = []

    def _fetch(symbol, trading_day, start_date, end_date, *, kind):  # noqa: ANN001, ARG001
        calls.append((symbol, kind))
        return _bars(["2026-07-07 14:00:00"])

    monkeypatch.setattr(market_service, "_fetch_cached_or_live", _fetch)

    report = market_service.refresh_intraday_min5_cache(
        trading_day="20260707",
        slot_at="2026-07-07 14:00:00",
        symbols=["600519", "603019", "000333"],
        benchmark_symbol="000300",
        core_symbols=["603019"],
    )

    assert report["attempted"]
    assert calls[:3] == [("000300", "index"), ("603019", "stock"), ("600519", "stock")]


def test_refresh_intraday_cache_respects_symbol_cooldown(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg(intraday_min5_refresh_sec=1, intraday_symbol_cooldown_sec=90))
    monkeypatch.setattr(market_service.time, "time", lambda: 1010.0)
    market_service._write_fetch_state(
        {
            "meta": {"last_refresh_attempt_at": 0.0},
            "symbols": {"20260707:stock:600519": {"last_fetch_at": 1000.0, "fail_count": 0}},
        }
    )
    calls: list[str] = []
    monkeypatch.setattr(
        market_service,
        "_fetch_cached_or_live",
        lambda symbol, *_, **__: calls.append(symbol) or _bars(["2026-07-07 14:00:00"]),
    )

    report = market_service.refresh_intraday_min5_cache(
        trading_day="20260707",
        slot_at="2026-07-07 14:00:00",
        symbols=["600519"],
        benchmark_symbol=None,
        core_symbols=["600519"],
    )

    assert calls == []
    assert report["cooldown"] == [{"symbol": "600519", "kind": "stock"}]


def test_refresh_intraday_cache_short_circuits_repeated_failures(monkeypatch, tmp_path):
    _isolate_data_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(market_service, "load_config", lambda: _cfg(intraday_min5_refresh_sec=120, intraday_symbol_cooldown_sec=0))
    monkeypatch.setattr(market_service.time, "time", lambda: 1050.0)
    market_service._write_fetch_state(
        {
            "meta": {"last_refresh_attempt_at": 0.0},
            "symbols": {"20260707:stock:600519": {"last_fetch_at": 1000.0, "fail_count": 2}},
        }
    )
    monkeypatch.setattr(
        market_service,
        "_fetch_cached_or_live",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("short-circuited symbol must not be fetched")),
    )

    report = market_service.refresh_intraday_min5_cache(
        trading_day="20260707",
        slot_at="2026-07-07 14:00:00",
        symbols=["600519"],
        benchmark_symbol=None,
        core_symbols=["600519"],
    )

    assert report["short_circuit"] == [{"symbol": "600519", "kind": "stock", "fail_count": 2}]
