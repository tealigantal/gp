from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import OrderedDict
import heapq
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, List, Tuple

import pandas as pd

from ..providers.boards import is_mainboard
from ..strategy.indicators import compute_indicators


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except Exception:
        return default
    if out != out or out in (float("inf"), float("-inf")):
        return default
    return out


def _date_iso(value: Any) -> str:
    return pd.to_datetime(value).date().isoformat()


def _normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if "." in raw:
        raw = raw.split(".", 1)[0]
    for prefix in ("sh", "sz", "bj"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


class ReadOnlyHistoryStore:
    """Read-only adapter over the production history DB for deterministic replay."""

    def __init__(self, path: str | Path, *, frame_cache_symbols: int = 0, history_window: int = 400):
        self.path = Path(path).resolve()
        if not self.path.exists():
            raise FileNotFoundError(f"history db not found: {self.path}")
        self.frame_cache_symbols = max(0, int(frame_cache_symbols))
        self.history_window = max(120, int(history_window))
        self._conn = sqlite3.connect(f"file:{self.path.as_posix()}?mode=ro", uri=True, timeout=30.0)
        self._query_by_symbol = self._load_query_map()
        self._date_cache: Dict[str, List[str]] = {}
        self._frame_cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._breadth_cache: Dict[int, Dict[str, Tuple[float, int, int]]] = {}
        self._ranking_cache: Dict[Tuple[int, int], Dict[str, List[str]]] = {}

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ReadOnlyHistoryStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _load_query_map(self) -> Dict[str, str]:
        selected: Dict[str, Tuple[str, str]] = {}
        rows = self._conn.execute("SELECT id, params, COALESCE(last_item_time, '') FROM queries").fetchall()
        for query_id, raw_params, last_item_time in rows:
            try:
                params = json.loads(raw_params or "{}")
            except Exception:
                continue
            if params.get("kind") != "daily":
                continue
            symbol = _normalize_symbol(params.get("symbol"))
            if not symbol or not is_mainboard(symbol):
                continue
            previous = selected.get(symbol)
            if previous is None or str(last_item_time) > previous[1]:
                selected[symbol] = (str(query_id), str(last_item_time))
        return {symbol: value[0] for symbol, value in selected.items()}

    def symbols(self) -> List[str]:
        return sorted(self._query_by_symbol)

    def _dates(self, symbol: str) -> List[str]:
        symbol = _normalize_symbol(symbol)
        cached = self._date_cache.get(symbol)
        if cached is not None:
            return cached
        query_id = self._query_by_symbol.get(symbol)
        if not query_id:
            return []
        rows = self._conn.execute(
            "SELECT item_time FROM items WHERE query_id=? ORDER BY item_time",
            (query_id,),
        ).fetchall()
        dates = [str(row[0])[:10] for row in rows if row and row[0]]
        self._date_cache[symbol] = dates
        return dates

    def trading_days(self, *, start: str | None = None, end: str | None = None) -> List[str]:
        reference = "000001" if "000001" in self._query_by_symbol else next(iter(self._query_by_symbol), "")
        days = self._dates(reference)
        lo = _date_iso(start) if start else "0000-01-01"
        hi = _date_iso(end) if end else "9999-12-31"
        return [day for day in days if lo <= day <= hi]

    def eligible_symbols(self, as_of: str, *, min_history: int = 120, limit: int = 0) -> List[str]:
        target = _date_iso(as_of)
        selected: List[str] = []
        for symbol in self.symbols():
            dates = self._dates(symbol)
            pos = bisect_left(dates, target)
            if pos >= len(dates) or dates[pos] != target or pos + 1 < int(min_history):
                continue
            selected.append(symbol)
            if limit > 0 and len(selected) >= limit:
                break
        return selected

    def _load_raw_frame(self, symbol: str) -> pd.DataFrame:
        symbol = _normalize_symbol(symbol)
        query_id = self._query_by_symbol.get(symbol)
        if not query_id:
            raise KeyError(f"daily history missing: {symbol}")
        rows = self._conn.execute(
            "SELECT payload FROM items WHERE query_id=? ORDER BY item_time",
            (query_id,),
        ).fetchall()
        payloads: List[Dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row[0])
            except Exception:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        frame = pd.DataFrame(payloads)
        if frame.empty or "date" not in frame.columns:
            raise ValueError(f"daily history invalid: {symbol}")
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame = frame.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        for key in ("open", "high", "low", "close", "volume", "amount"):
            if key in frame.columns:
                frame[key] = pd.to_numeric(frame[key], errors="coerce")
        self._date_cache[symbol] = frame["date"].dt.strftime("%Y-%m-%d").tolist()
        return frame

    def _load_frame(self, symbol: str) -> pd.DataFrame:
        symbol = _normalize_symbol(symbol)
        cached = self._frame_cache.get(symbol)
        if cached is not None:
            self._frame_cache.move_to_end(symbol)
            return cached
        frame = self._load_raw_frame(symbol)
        frame = compute_indicators(frame).reset_index(drop=True)
        self._frame_cache[symbol] = frame
        self._frame_cache.move_to_end(symbol)
        if self.frame_cache_symbols > 0:
            while len(self._frame_cache) > self.frame_cache_symbols:
                self._frame_cache.popitem(last=False)
        return frame

    def prepare_market_index(self, days: Iterable[str], *, min_history: int = 120, rank_limit: int = 200) -> None:
        requested = {_date_iso(day) for day in days}
        if not requested:
            return
        history_key = max(2, int(min_history))
        rank_key = (history_key, int(rank_limit))
        totals: Dict[str, List[float | int]] = {day: [0.0, 0, 0] for day in requested}
        rankings: Dict[str, List[Tuple[float, int, str]]] = {day: [] for day in requested}
        for symbol in self.symbols():
            frame = self._load_raw_frame(symbol)
            closes = pd.to_numeric(frame["close"], errors="coerce")
            changes = (closes / closes.shift(1) - 1.0) * 100.0
            if "amount" in frame.columns:
                liquidity = pd.to_numeric(frame["amount"], errors="coerce").rolling(20, min_periods=1).mean()
            else:
                liquidity = (
                    pd.to_numeric(frame.get("volume"), errors="coerce")
                    * pd.to_numeric(frame.get("close"), errors="coerce")
                ).rolling(20, min_periods=1).mean()
            date_values = frame["date"].dt.strftime("%Y-%m-%d")
            for index in range(history_key - 1, len(frame)):
                day = str(date_values.iloc[index])
                if day not in requested:
                    continue
                change = _safe_float(changes.iloc[index], float("nan"))
                if change == change:
                    bucket = totals[day]
                    bucket[0] = float(bucket[0]) + change
                    bucket[1] = int(bucket[1]) + (1 if change > 0.0 else 0)
                    bucket[2] = int(bucket[2]) + 1
                liquidity_value = _safe_float(liquidity.iloc[index], 0.0)
                heap = rankings[day]
                item = (liquidity_value, -int(symbol), symbol)
                if int(rank_limit) <= 0:
                    heap.append(item)
                elif len(heap) < int(rank_limit):
                    heapq.heappush(heap, item)
                elif item > heap[0]:
                    heapq.heapreplace(heap, item)
        breadth = self._breadth_cache.setdefault(history_key, {})
        for day, value in totals.items():
            breadth[day] = (float(value[0]), int(value[1]), int(value[2]))
        self._ranking_cache[rank_key] = {
            day: [symbol for _, _, symbol in sorted(values, key=lambda item: (-item[0], item[2]))]
            for day, values in rankings.items()
        }

    def daily_ohlcv(
        self,
        symbol: str,
        as_of: str | None = None,
        min_len: int = 250,
        *,
        prefer_cache_only: bool = False,
        force_network: bool = False,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        del prefer_cache_only, force_network
        frame = self._load_frame(symbol)
        target = _date_iso(as_of) if as_of else _date_iso(frame["date"].iloc[-1])
        dates = frame["date"].dt.strftime("%Y-%m-%d").tolist()
        end = bisect_right(dates, target)
        start = max(0, end - max(self.history_window, int(min_len)))
        scoped = frame.iloc[start:end].copy().reset_index(drop=True)
        last_date = _date_iso(scoped["date"].iloc[-1]) if not scoped.empty else None
        current = bool(last_date == target)
        meta = {
            "source": "history_db_read_only",
            "history_db": str(self.path),
            "len": len(scoped),
            "rows_total": len(scoped),
            "requested_as_of": target,
            "target_trading_day": target,
            "last_item_time": last_date,
            "freshness_state": "current" if current else "stale",
            "strict_blocked": not current or len(scoped) < int(min_len),
            "insufficient_history": len(scoped) < int(min_len),
            "network_attempted": False,
        }
        scoped.attrs.update(meta)
        return scoped, meta

    def _full_breadth(self, min_history: int) -> Dict[str, Tuple[float, int, int]]:
        key = max(2, int(min_history))
        cached = self._breadth_cache.get(key)
        if cached is not None:
            return cached
        totals: Dict[str, List[float | int]] = {}
        for symbol in self.symbols():
            frame = self._load_frame(symbol)
            closes = pd.to_numeric(frame["close"], errors="coerce")
            changes = (closes / closes.shift(1) - 1.0) * 100.0
            dates = frame["date"].dt.strftime("%Y-%m-%d")
            for index in range(key - 1, len(frame)):
                change = _safe_float(changes.iloc[index], float("nan"))
                if change != change:
                    continue
                day = str(dates.iloc[index])
                bucket = totals.setdefault(day, [0.0, 0, 0])
                bucket[0] = float(bucket[0]) + change
                bucket[1] = int(bucket[1]) + (1 if change > 0.0 else 0)
                bucket[2] = int(bucket[2]) + 1
        normalized = {day: (float(value[0]), int(value[1]), int(value[2])) for day, value in totals.items()}
        self._breadth_cache[key] = normalized
        return normalized

    def market_context(
        self,
        as_of: str,
        symbols: Iterable[str] | None = None,
        *,
        min_history: int = 120,
    ) -> Dict[str, Any]:
        target = _date_iso(as_of)
        changes: List[float] = []
        if symbols is None:
            total, up_count, count = self._full_breadth(min_history).get(target, (0.0, 0, 0))
            mean_change = float(total / count) if count else None
            up_ratio = float(up_count / count) if count else None
            breadth_count = count
        else:
            for symbol in symbols:
                frame = self._load_frame(symbol)
                dates = frame["date"].dt.strftime("%Y-%m-%d").tolist()
                pos = bisect_left(dates, target)
                if pos <= 0 or pos >= len(dates) or dates[pos] != target:
                    continue
                previous = _safe_float(frame["close"].iloc[pos - 1], 0.0)
                current = _safe_float(frame["close"].iloc[pos], 0.0)
                if previous > 0.0 and current > 0.0:
                    changes.append((current / previous - 1.0) * 100.0)
            mean_change = float(sum(changes) / len(changes)) if changes else None
            up_ratio = float(sum(1 for value in changes if value > 0.0) / len(changes)) if changes else None
            breadth_count = len(changes)
        if mean_change is None or up_ratio is None:
            return {
                "as_of": target,
                "grade": "C",
                "market_regime": "C",
                "regime_reasons": ["historical_breadth_missing"],
                "raw": {"mean_chg": None, "up_ratio": None, "breadth_count": breadth_count},
                "hard_block": True,
                "hard_block_reasons": ["historical_breadth_missing"],
            }
        grade = "A" if mean_change > 1.0 and up_ratio > 0.60 else "B" if mean_change > 0.3 and up_ratio > 0.55 else "C" if mean_change > -0.3 and up_ratio > 0.45 else "D"
        return {
            "as_of": target,
            "grade": grade,
            "market_regime": grade,
            "regime_reasons": [f"historical_mean_change={mean_change:.4f}", f"historical_up_ratio={up_ratio:.4f}"],
            "raw": {"mean_chg": mean_change, "up_ratio": up_ratio, "breadth_count": breadth_count},
            "snapshot": {"source": "history_db_read_only", "rows": breadth_count, "ok": True},
        }

    def rank_universe(self, as_of: str, symbols: Iterable[str], *, limit: int = 200) -> List[str]:
        """Causal production-like liquidity prefilter using data visible at T."""
        target = _date_iso(as_of)
        allowed = set(symbols)
        for (_min_history, cached_limit), by_day in self._ranking_cache.items():
            if cached_limit == int(limit) and target in by_day:
                return [symbol for symbol in by_day[target] if symbol in allowed]
        ranked: List[Tuple[float, str]] = []
        for symbol in allowed:
            frame = self._load_frame(symbol)
            dates = frame["date"].dt.strftime("%Y-%m-%d").tolist()
            pos = bisect_left(dates, target)
            if pos >= len(dates) or dates[pos] != target:
                continue
            recent = frame.iloc[max(0, pos - 19) : pos + 1]
            if "amount" in recent.columns:
                liquidity = _safe_float(pd.to_numeric(recent["amount"], errors="coerce").mean(), 0.0)
            else:
                liquidity = 0.0
            if liquidity <= 0.0 and {"volume", "close"}.issubset(recent.columns):
                liquidity = _safe_float(
                    (pd.to_numeric(recent["volume"], errors="coerce") * pd.to_numeric(recent["close"], errors="coerce")).mean(),
                    0.0,
                )
            ranked.append((liquidity, _normalize_symbol(symbol)))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        selected = [symbol for _, symbol in ranked]
        return selected[: int(limit)] if int(limit) > 0 else selected

    @staticmethod
    def _entry_fill(row: pd.Series, plan: Dict[str, Any]) -> float | None:
        entry = dict(plan.get("entry") or plan.get("entry_plan") or {})
        open_price = _safe_float(row.get("open"), 0.0)
        low = _safe_float(row.get("low"), open_price)
        high = _safe_float(row.get("high"), open_price)
        exact = _safe_float(entry.get("price") or entry.get("trigger_price"), 0.0)
        band_low = _safe_float(entry.get("low") or entry.get("entry_low"), exact)
        band_high = _safe_float(entry.get("high") or entry.get("entry_high"), exact)
        if exact > 0.0 and low <= exact <= high:
            return min(open_price, exact) if open_price > 0.0 else exact
        if band_low > 0.0 and band_high >= band_low and low <= band_high and high >= band_low:
            if band_low <= open_price <= band_high:
                return open_price
            return band_high
        return None

    def future_outcome(self, pick: Dict[str, Any], *, as_of: str, horizon: int = 5, friction_bps: float = 30.0) -> Dict[str, Any]:
        symbol = _normalize_symbol(pick.get("symbol") or pick.get("code"))
        try:
            frame = self._load_frame(symbol)
        except Exception as ex:
            return {"complete": False, "reason": f"daily_data_unavailable:{type(ex).__name__}", "symbol": symbol}
        target = _date_iso(as_of)
        dates = frame["date"].dt.strftime("%Y-%m-%d").tolist()
        pos = bisect_left(dates, target)
        if pos >= len(dates) or dates[pos] != target:
            return {"complete": False, "reason": "as_of_not_found", "symbol": symbol}
        if pos + int(horizon) >= len(frame):
            return {"complete": False, "reason": "future_window_not_available", "symbol": symbol}
        entry_close = _safe_float(frame["close"].iloc[pos], 0.0)
        future = frame.iloc[pos + 1 : pos + int(horizon) + 1]
        if entry_close <= 0.0 or future.empty:
            return {"complete": False, "reason": "entry_price_invalid", "symbol": symbol}
        closes = pd.to_numeric(future["close"], errors="coerce")
        highs = pd.to_numeric(future["high"], errors="coerce")
        lows = pd.to_numeric(future["low"], errors="coerce")
        fill = self._entry_fill(future.iloc[0], pick.get("trade_plan") or pick)
        stop = dict((pick.get("trade_plan") or {}).get("stop") or pick.get("stop_plan") or {})
        take = dict((pick.get("trade_plan") or {}).get("take_profit") or pick.get("take_profit_plan") or {})
        stop_price = _safe_float(stop.get("price") or stop.get("stop_price"), 0.0)
        targets = take.get("targets") if isinstance(take.get("targets"), list) else []
        take_price = _safe_float((targets or [take.get("price") or take.get("take1")])[0], 0.0)
        net_return_3d = None
        exit_reason = "not_filled"
        if fill is not None and fill > 0.0:
            exit_price = _safe_float(closes.iloc[min(2, len(closes) - 1)], 0.0)
            exit_reason = "t3_close"
            for _, row in future.iloc[:3].iterrows():
                row_low = _safe_float(row.get("low"), 0.0)
                row_high = _safe_float(row.get("high"), 0.0)
                if stop_price > 0.0 and row_low <= stop_price:
                    exit_price = stop_price
                    exit_reason = "stop_first_conservative"
                    break
                if take_price > 0.0 and row_high >= take_price:
                    exit_price = take_price
                    exit_reason = "take_profit"
                    break
            net_return_3d = float(exit_price / fill - 1.0 - float(friction_bps) / 10000.0)
        return {
            "complete": True,
            "symbol": symbol,
            "entry_date": target,
            "entry_close": entry_close,
            "return_1d": _safe_float(closes.iloc[0] / entry_close - 1.0),
            "return_3d": _safe_float(closes.iloc[min(2, len(closes) - 1)] / entry_close - 1.0),
            "return_5d": _safe_float(closes.iloc[min(4, len(closes) - 1)] / entry_close - 1.0),
            "max_profit": _safe_float(highs.max() / entry_close - 1.0),
            "max_drawdown": _safe_float(lows.min() / entry_close - 1.0),
            "success": bool(_safe_float(closes.iloc[min(2, len(closes) - 1)] / entry_close - 1.0) > 0.0),
            "filled": fill is not None,
            "fill_price": fill,
            "net_return_3d": net_return_3d,
            "exit_reason": exit_reason,
            "friction_bps": float(friction_bps),
            "matured_at": _date_iso(future["date"].iloc[-1]),
            "data_meta": {"source": "history_db_read_only", "history_db": str(self.path)},
        }
