from __future__ import annotations

import pandas as pd

from gp_assistant.providers.akshare_provider import AkShareProvider


class _FakeAkMinutePrimary:
    def __init__(self) -> None:
        self.primary_calls: list[dict] = []
        self.fallback_calls: list[dict] = []

    def stock_zh_a_minute(self, *, symbol, period, adjust):  # noqa: ANN001
        self.primary_calls.append({"symbol": symbol, "period": period, "adjust": adjust})
        return pd.DataFrame(
            [
                {"day": "2026-07-07 09:25:00", "open": 9.9, "high": 10.0, "low": 9.8, "close": 9.95, "volume": 80},
                {"day": "2026-07-07 11:25:00", "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 100},
                {"day": "2026-07-07 11:30:00", "open": 10.1, "high": 10.4, "low": 10.0, "close": 10.3, "volume": 150},
                {"day": "2026-07-07 13:05:00", "open": 10.3, "high": 10.5, "low": 10.2, "close": 10.4, "volume": 180},
            ]
        )

    def stock_zh_a_hist_min_em(self, **kwargs):  # noqa: ANN003
        self.fallback_calls.append(kwargs)
        raise AssertionError("fallback should not be called when primary succeeds")

    def index_zh_a_hist_min_em(self, **kwargs):  # noqa: ANN003
        self.fallback_calls.append(kwargs)
        raise AssertionError("index fallback should not be called when primary succeeds")


class _FakeAkMinuteFallback:
    def __init__(self) -> None:
        self.primary_calls: list[dict] = []
        self.fallback_calls: list[dict] = []

    def stock_zh_a_minute(self, *, symbol, period, adjust):  # noqa: ANN001
        self.primary_calls.append({"symbol": symbol, "period": period, "adjust": adjust})
        raise RuntimeError("primary down")

    def stock_zh_a_hist_min_em(self, **kwargs):  # noqa: ANN003
        self.fallback_calls.append(kwargs)
        return pd.DataFrame(
            [
                {"时间": "2026-07-07 11:25:00", "开盘": 10.0, "最高": 10.2, "最低": 9.9, "收盘": 10.1, "成交量": 100, "成交额": 1010},
                {"时间": "2026-07-07 11:30:00", "开盘": 10.1, "最高": 10.4, "最低": 10.0, "收盘": 10.3, "成交量": 150, "成交额": 1545},
            ]
        )


def _provider(fake_ak) -> AkShareProvider:  # noqa: ANN001
    provider = AkShareProvider(timeout_sec=3)
    provider._import = lambda: fake_ak  # type: ignore[method-assign]
    provider._with_requests_timeout = lambda fn: fn()  # type: ignore[method-assign]
    return provider


def test_stock_minute_provider_prefers_stock_zh_a_minute_and_standardizes_window():
    fake = _FakeAkMinutePrimary()
    df = _provider(fake).get_minute_bars_5m(
        "600519",
        "2026-07-07 11:25:00",
        "2026-07-07 11:30:00",
    )

    assert fake.primary_calls == [{"symbol": "sh600519", "period": "5", "adjust": ""}]
    assert fake.fallback_calls == []
    assert list(df["trade_time"].dt.strftime("%H:%M")) == ["11:25", "11:30"]
    assert list(df["vol"]) == [100, 150]
    assert list(df["amount"]) == [1010.0, 1545.0]


def test_stock_minute_provider_falls_back_to_hist_min_em():
    fake = _FakeAkMinuteFallback()
    df = _provider(fake).get_minute_bars_5m(
        "600519",
        "2026-07-07 11:25:00",
        "2026-07-07 11:30:00",
    )

    assert fake.primary_calls == [{"symbol": "sh600519", "period": "5", "adjust": ""}]
    assert fake.fallback_calls[0]["symbol"] == "600519"
    assert len(df) == 2
    assert list(df["amount"]) == [1010, 1545]


def test_index_minute_provider_uses_prefixed_stock_minute_source():
    fake = _FakeAkMinutePrimary()
    df = _provider(fake).get_index_minute_bars_5m(
        "000300",
        "2026-07-07 11:25:00",
        "2026-07-07 11:30:00",
    )

    assert fake.primary_calls == [{"symbol": "sh000300", "period": "5", "adjust": ""}]
    assert fake.fallback_calls == []
    assert len(df) == 2
