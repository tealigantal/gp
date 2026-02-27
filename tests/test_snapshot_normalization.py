import pandas as pd

from src.gp_assistant.providers.akshare_provider import AkShareProvider


def test_snapshot_normalization_sina():
    df = pd.DataFrame({
        "代码": ["sz301550", "bj430017", "sh600519"],
        "名称": ["X", "Y", "Z"],
        "最新价": [10.5, 5.2, 1800.0],
        "涨跌幅": ["1.23%", "-2.5%", 0.5],
        "涨跌额": [0.13, -0.10, 9.0],
        "成交量": [10000, 20000, 30000],
        "成交额": [1e6, 2e6, 3e6],
        "时间": ["10:30", "10:31", "10:32"],
    })
    p = AkShareProvider()
    out = p._standardize_spot_snapshot(df, route="sina")
    assert set(["code", "symbol", "name", "price", "pct_chg", "chg", "volume", "amount", "ts"]).issubset(out.columns)
    codes = list(out["code"])[:3]
    assert "301550" in codes and "430017" in codes
    assert pd.api.types.is_numeric_dtype(out["pct_chg"])  # coerce percent


def test_snapshot_normalization_em():
    df = pd.DataFrame({
        "代码": ["600519", "000001"],
        "名称": ["贵州茅台", "平安银行"],
        "最新价": [1800.0, 12.3],
        "涨跌幅": [1.2, -0.5],
        "涨跌额": [10.0, -0.06],
        "成交量": [30000, 50000],
        "成交额": [3e9, 5e8],
    })
    p = AkShareProvider()
    out = p._standardize_spot_snapshot(df, route="em")
    assert set(["code", "symbol", "name", "price", "pct_chg", "amount"]).issubset(out.columns)
    assert list(out["symbol"]) == ["sh600519", "sz000001"]
