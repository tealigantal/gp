import pandas as pd

from gp_assistant.tools.market_data import normalize_daily_ohlcv


def make_df(vol_col: str = "volume", with_amount: bool = False):
    data = {
        "date": ["2024-01-03", "2024-01-01", "2024-01-02", "2024-01-02"],
        "open": [10, 9, 9.5, 9.5],
        "high": [11, 10, 10, 10],
        "low": [9, 8.5, 9, 9],
        "close": [10.5, 9.8, 9.7, 9.7],
    }
    if vol_col == "vol":
        data["vol"] = [1000, 900, 950, 950]  # hands
    else:
        data["volume"] = [100000, 90000, 95000, 95000]  # shares
    if with_amount:
        data["amount"] = [x * 10 for x in (data.get("volume") or data.get("vol"))]
    return pd.DataFrame(data)


def test_normalize_sorts_and_dedups():
    df = make_df()
    out, meta = normalize_daily_ohlcv(df, volume_unit='share')
    # unique by date and ascending
    dates = list(out["date"].dt.strftime("%Y-%m-%d"))
    assert dates == ["2024-01-01", "2024-01-02", "2024-01-03"]
    assert meta["volume_unit"] == "share"


def test_normalize_estimates_amount_when_missing():
    df = make_df()
    out, meta = normalize_daily_ohlcv(df, volume_unit='share')
    assert "amount" in out.columns
    assert meta["amount_is_estimated"] is True


def test_normalize_converts_hands_to_shares_when_vol_present():
    df = make_df(vol_col="vol")
    out, meta = normalize_daily_ohlcv(df, volume_unit='hand')
    # The first row in chronological order is 2024-01-01 with vol=900 hands
    first = out.iloc[0]
    assert abs(first["volume"] - 900 * 100) < 1e-6
    assert meta["volume_unit"] == "share"


def test_normalize_unknown_unit_raises():
    df = make_df()
    import pytest
    with pytest.raises(Exception):
        normalize_daily_ohlcv(df, volume_unit='unknown')
