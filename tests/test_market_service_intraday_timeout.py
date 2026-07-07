from __future__ import annotations

from types import SimpleNamespace

from gp_assistant.evidence import market_service


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


def test_fetch_intraday_bundle_short_circuits_when_symbol_bars_incomplete(monkeypatch):
    monkeypatch.setattr(market_service, "load_config", lambda: SimpleNamespace(intraday_benchmark_symbol="000300"))
    monkeypatch.setattr(market_service, "fetch_minute_bars_5m", lambda symbols, trading_day, *, slot_at: {})
    monkeypatch.setattr(
        market_service,
        "fetch_benchmark_bars_5m",
        lambda *_, **__: (_ for _ in ()).throw(AssertionError("benchmark should be skipped")),
    )
    monkeypatch.setattr(
        market_service,
        "fetch_snapshot",
        lambda: (_ for _ in ()).throw(AssertionError("snapshot should be skipped")),
    )

    bundle = market_service.fetch_intraday_bundle(
        trading_day="20260707",
        slot_at="2026-07-07 13:10:00",
        symbols=["600519", "000001"],
    )

    assert bundle["symbols_expected"] == 2
    assert bundle["symbols_received"] == 0
    assert bundle["benchmark_received"] is False
    assert "benchmark_skipped:incomplete_symbols" in bundle["errors"]
    assert "snapshot_skipped:incomplete_symbols" in bundle["errors"]
