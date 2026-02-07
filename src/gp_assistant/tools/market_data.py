from __future__ import annotations

from typing import Any
import pandas as pd

from ..core.types import ToolResult
from ..core.errors import DataProviderError, GPAssistantError
from ..providers.factory import get_provider


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

