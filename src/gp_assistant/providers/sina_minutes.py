"""One unadjusted five-minute source for stocks and CSI300. No route retry."""
from __future__ import annotations

import json
from datetime import datetime
from time import monotonic
from zoneinfo import ZoneInfo
import pandas as pd
import requests

SOURCE = "sina:CN_MarketDataService.getKLineData:5m"
URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData"
SHANGHAI = ZoneInfo("Asia/Shanghai")


class MinuteDataError(ValueError):
    pass


class SinaMinuteProvider:
    def fetch(self, symbol: str, *, index: bool = False):
        if len(symbol) != 6 or not symbol.isdigit():
            raise MinuteDataError("invalid_symbol")
        prefixed = ("sh" if index or symbol.startswith("6") else "sz") + symbol
        started = monotonic()
        response = requests.get(URL, params={"symbol": prefixed, "scale": 5, "ma": "no", "datalen": 240}, timeout=8)
        response.raise_for_status()
        body = response.text
        try:
            rows = json.loads(body.split("=(", 1)[1].rsplit(");", 1)[0])
        except (ValueError, IndexError) as exc:
            raise MinuteDataError("sina_response_invalid") from exc
        if not isinstance(rows, list) or not rows:
            raise MinuteDataError("sina_minutes_empty")
        return pd.DataFrame(rows).rename(columns={"day": "trade_time", "volume": "vol"}), datetime.now(SHANGHAI), (monotonic() - started) * 1000
