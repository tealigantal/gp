# 简介：工具 - 行情数据标准化/读取辅助，供 CLI 与引擎复用。
from __future__ import annotations

from typing import Any, Tuple, Dict, Optional
import pandas as pd

from ..core.types import ToolResult
from ..core.errors import DataProviderError, GPAssistantError
from ..providers.factory import get_provider
from ..core.config import load_config


def normalize_daily_ohlcv(df: pd.DataFrame, *, volume_unit: Optional[str] = None) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Normalize raw daily OHLCV to a canonical schema.

    - Required columns: date, open, high, low, close, volume
    - Optional: amount
    - date: pandas datetime, ascending, unique (drop duplicates keeping last)
    - volume: unified to shares; if source used 'vol' (hand), convert x100
    - amount: if missing, estimate via vwap_day=((H+L+C)/3) * volume
    Returns: (df_norm, meta)
    meta includes: volume_unit='share', amount_is_estimated=bool
    """
    if df is None or not isinstance(df, pd.DataFrame):  # pragma: no cover
        raise GPAssistantError("normalize_daily_ohlcv: df 不能为空")

    src = df.copy()
    meta: Dict[str, Any] = {}

    # Rename common variants
    rename_map = {
        "日期": "date",
        "date": "date",
        "trade_date": "date",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "vol": "volume",  # typical provider hands
    }
    for k, v in rename_map.items():
        if k in src.columns and v not in src.columns:
            src[v] = src[k]

    required = ["date", "open", "high", "low", "close"]
    missing = [c for c in required if c not in src.columns]
    if missing:
        raise GPAssistantError(f"原始数据缺少必要列: {missing}")

    # Ensure volume column exists (from either volume or vol)
    if "volume" not in src.columns:
        # try common other names
        if "成交量" in src.columns:
            src["volume"] = src["成交量"]
        else:
            raise GPAssistantError("原始数据缺少 volume/成交量 列")

    # Handle date
    try:
        src["date"] = pd.to_datetime(src["date"])
    except Exception:  # noqa: BLE001
        src["date"] = pd.to_datetime(src["date"].astype(str), errors="coerce")
    if src["date"].isna().any():
        raise GPAssistantError("存在无效日期，无法标准化")

    # Drop duplicates on date, keep last, then sort ascending
    src = src.drop_duplicates(subset=["date"], keep="last").sort_values("date").reset_index(drop=True)

    # Volume unit unification via priority: provider meta -> function arg -> config -> error
    cfg = load_config()
    unit = (
        (df.attrs.get("volume_unit") if isinstance(df.attrs, dict) else None)
        or volume_unit
        or getattr(cfg, "default_volume_unit", "share")
    )
    unit = str(unit).lower() if unit else None
    if unit not in {"hand", "share"}:
        raise GPAssistantError("未知的成交量单位，请设置 config.default_volume_unit=hand|share 或传入 volume_unit")
    converted = False
    if unit == "hand":
        src["volume"] = pd.to_numeric(src["volume"], errors="coerce").astype(float) * 100.0
        meta["volume_unit_before"] = "hand"
        unit = "share"
        converted = True
    meta["volume_unit"] = unit
    meta["volume_converted"] = converted
    # propagate attrs
    try:
        src.attrs["volume_unit_before"] = meta.get("volume_unit_before")
        src.attrs["volume_unit"] = meta["volume_unit"]
        src.attrs["volume_converted"] = converted
    except Exception:
        pass

    # Ensure numeric types
    for col in ["open", "high", "low", "close", "volume"]:
        src[col] = pd.to_numeric(src[col], errors="coerce")
    if src[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise GPAssistantError("存在空值：open/high/low/close/volume，无法标准化")

    # Amount handling
    amount_is_estimated = False
    if "amount" not in src.columns:
        vwap = (src["high"] + src["low"] + src["close"]) / 3.0
        src["amount"] = (src["volume"].astype(float) * vwap.astype(float))
        amount_is_estimated = True
    else:
        # Clean amount
        src["amount"] = pd.to_numeric(src["amount"], errors="coerce")
        if src["amount"].isna().any():
            vwap = (src["high"] + src["low"] + src["close"]) / 3.0
            src["amount"] = src["amount"].fillna(src["volume"].astype(float) * vwap.astype(float))
            amount_is_estimated = True
    meta["amount_is_estimated"] = bool(amount_is_estimated)

    # Do not enforce minimal length here; later stages may flag insufficient history

    # Attach attrs too for propagation
    try:
        src.attrs.update(meta)
    except Exception:
        pass

    return src, meta

def run_data(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    start = args.get("start")
    end = args.get("end")
    if not symbol:
        return ToolResult(ok=False, message="缺少参数: --symbol")
    provider = get_provider()
    try:
        df: pd.DataFrame = provider.get_daily(symbol=symbol, start=start, end=end)
        head = df.head(5).to_dict(orient="records")
        return ToolResult(
            ok=True,
            message=f"数据获取成功: provider={provider.name}, rows={len(df)}",
            data={"sample": head},
        )
    except DataProviderError as e:
        return ToolResult(ok=False, message=f"数据源错误: {e}")
    except Exception as e:  # noqa: BLE001
        return ToolResult(ok=False, message=f"未知错误: {e}")
