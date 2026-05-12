from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from ..providers.akshare_provider import AkShareProvider


_SYMBOL_RE = re.compile(r"(?<!\d)(?:60|68|00|30)\d{4}(?!\d)")
_NUMBER_RE = r"([0-9]+(?:\.[0-9]+)?)"


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _trade_day_ymd(trade_day: str | None) -> str:
    text = str(trade_day or "").strip().replace("-", "")
    if re.fullmatch(r"\d{8}", text):
        return text
    return datetime.now().strftime("%Y%m%d")


def _trade_day_iso(trade_day: str | None) -> str:
    ymd = _trade_day_ymd(trade_day)
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def extract_user_quote(user_message: str) -> Dict[str, Any]:
    text = str(user_message or "")
    symbols = _SYMBOL_RE.findall(text)

    def find_price(patterns: list[str]) -> Optional[float]:
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                parsed = _as_float(match.group(1))
                if parsed is not None:
                    return parsed
        return None

    day_high = find_price([
        rf"最高价?\s*{_NUMBER_RE}",
        rf"高点\s*{_NUMBER_RE}",
    ])
    current_price = find_price([
        rf"现在(?:是|价|价格)?\s*{_NUMBER_RE}",
        rf"现价\s*{_NUMBER_RE}",
        rf"当前(?:是|价|价格)?\s*{_NUMBER_RE}",
        rf"目前(?:是|价|价格)?\s*{_NUMBER_RE}",
    ])
    day_low = find_price([
        rf"最低价?\s*{_NUMBER_RE}",
        rf"低点\s*{_NUMBER_RE}",
    ])
    return {
        "source": "user",
        "symbol": symbols[0] if symbols else None,
        "current_price": current_price,
        "day_high": day_high,
        "day_low": day_low,
        "stable_hint": any(token in text for token in ("稳定", "横盘", "震荡", "稳住")),
        "quote_time_missing": current_price is not None,
        "raw_text": text,
    }


def _normalize_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().lower()
    if "." in text:
        text = text.split(".", 1)[0]
    for prefix in ("sh", "sz", "bj"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def _fetch_minute_quote(provider: AkShareProvider, symbol: str, trade_day: str | None) -> Dict[str, Any]:
    ak = provider._import()
    code = _normalize_symbol(symbol)
    day = _trade_day_iso(trade_day)
    start = f"{day} 09:30:00"
    end = f"{day} 15:00:00"
    df = provider._with_requests_timeout(
        lambda: ak.stock_zh_a_hist_min_em(
            symbol=code,
            start_date=start,
            end_date=end,
            period="1",
            adjust="",
        )
    )
    if not isinstance(df, pd.DataFrame) or df.empty:
        raise RuntimeError("minute_quote_empty")
    required = {"时间", "收盘", "最高", "最低"}
    if not required <= set(map(str, df.columns)):
        raise RuntimeError("minute_quote_schema_missing")
    data = df.copy()
    data["时间"] = pd.to_datetime(data["时间"], errors="coerce")
    data = data.dropna(subset=["时间"]).sort_values("时间")
    if data.empty:
        raise RuntimeError("minute_quote_time_missing")
    latest = data.iloc[-1]
    latest_time = pd.to_datetime(latest["时间"]).strftime("%Y-%m-%d %H:%M:%S")
    current_price = _as_float(latest.get("收盘"))
    if current_price is None:
        raise RuntimeError("minute_quote_price_missing")
    return {
        "source": "akshare:minute_1m",
        "verified": True,
        "status": "minute_ok",
        "symbol": code,
        "latest_time": latest_time,
        "current_price": current_price,
        "day_high": _as_float(pd.to_numeric(data["最高"], errors="coerce").max()),
        "day_low": _as_float(pd.to_numeric(data["最低"], errors="coerce").min()),
        "average_price": _as_float(latest.get("均价")),
        "rows": int(len(data)),
        "trade_day": _trade_day_ymd(trade_day),
    }


def _fetch_bid_ask_quote(provider: AkShareProvider, symbol: str) -> Dict[str, Any]:
    ak = provider._import()
    code = _normalize_symbol(symbol)
    df = provider._with_requests_timeout(lambda: ak.stock_bid_ask_em(symbol=code))
    if not isinstance(df, pd.DataFrame) or df.empty or not {"item", "value"} <= set(map(str, df.columns)):
        raise RuntimeError("bid_ask_quote_schema_missing")
    values = {str(row["item"]): row["value"] for _, row in df.iterrows()}
    current_price = _as_float(values.get("最新") or values.get("最新价") or values.get("现价"))
    day_high = _as_float(values.get("最高"))
    day_low = _as_float(values.get("最低"))
    if current_price is None and day_high is None and day_low is None:
        raise RuntimeError("bid_ask_quote_price_missing")
    return {
        "source": "akshare:bid_ask",
        "verified": True,
        "status": "bid_ask_ok",
        "symbol": code,
        "latest_time": None,
        "current_price": current_price,
        "day_high": day_high,
        "day_low": day_low,
        "open_price": _as_float(values.get("今开")),
        "prev_close": _as_float(values.get("昨收")),
        "volume_ratio": _as_float(values.get("量比")),
    }


def _attach_user_quote(quote: Dict[str, Any], user_quote: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(quote)
    out["user_quote"] = user_quote
    user_price = _as_float(user_quote.get("current_price"))
    live_price = _as_float(out.get("current_price"))
    if user_price is not None and live_price is not None:
        diff = live_price - user_price
        threshold = max(0.05, abs(user_price) * 0.003)
        out["user_quote_diff"] = round(diff, 4)
        out["user_quote_mismatch"] = abs(diff) > threshold
    else:
        out["user_quote_mismatch"] = False
    return out


def build_live_quote_snapshot(
    *,
    symbol: str,
    user_message: str,
    trade_day: str | None = None,
    provider: AkShareProvider | None = None,
    use_minute: bool | None = None,
    use_bid_ask: bool = True,
) -> Dict[str, Any]:
    user_quote = extract_user_quote(user_message)
    provider = provider or AkShareProvider(timeout_sec=1)
    errors: list[str] = []
    minute_enabled = (
        use_minute
        if use_minute is not None
        else str(os.getenv("GP_LIVE_QUOTE_USE_MINUTE", "1")).strip().lower() not in {"0", "false", "no"}
    )

    if minute_enabled:
        for attempt in range(2):
            try:
                return _attach_user_quote(_fetch_minute_quote(provider, symbol, trade_day), user_quote)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"minute[{attempt + 1}]:{type(exc).__name__}: {exc}")

    if use_bid_ask:
        try:
            return _attach_user_quote(_fetch_bid_ask_quote(provider, symbol), user_quote)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"bid_ask:{type(exc).__name__}: {exc}")

    if user_quote.get("current_price") is not None or user_quote.get("day_high") is not None:
        return {
            "source": "user",
            "verified": False,
            "status": "user_quote_only",
            "symbol": _normalize_symbol(symbol) or user_quote.get("symbol"),
            "current_price": user_quote.get("current_price"),
            "day_high": user_quote.get("day_high"),
            "day_low": user_quote.get("day_low"),
            "latest_time": None,
            "user_quote": user_quote,
            "errors": errors,
        }

    return {
        "source": "none",
        "verified": False,
        "status": "quote_unavailable",
        "symbol": _normalize_symbol(symbol),
        "current_price": None,
        "day_high": None,
        "day_low": None,
        "latest_time": None,
        "user_quote": user_quote,
        "errors": errors,
    }
