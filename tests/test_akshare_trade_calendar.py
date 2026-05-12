from types import SimpleNamespace

import pandas as pd

from src.providers.akshare_provider import AkshareProvider


def test_akshare_trade_calendar_expands_to_full_date_range():
    provider = AkshareProvider.__new__(AkshareProvider)
    provider.ak = SimpleNamespace(
        tool_trade_date_hist_sina=lambda: pd.DataFrame(
            {
                "trade_date": pd.to_datetime(
                    [
                        "2026-04-30",
                        "2026-05-06",
                        "2026-05-07",
                    ]
                ).date
            }
        )
    )

    cal = provider.get_trade_calendar("20260430", "20260507")

    by_day = dict(zip(cal["cal_date"], cal["is_open"]))
    assert by_day["20260430"] == 1
    assert by_day["20260501"] == 0
    assert by_day["20260504"] == 0
    assert by_day["20260505"] == 0
    assert by_day["20260506"] == 1
    assert by_day["20260507"] == 1
