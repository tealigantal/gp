"""Causal evidence calculations. No trend voting, score, or entry decision."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from hashlib import sha256
import json
import numpy as np
import pandas as pd

from ..contracts.entry import EntryEvidence
from ..providers.sina_minutes import MinuteDataError, SOURCE, SHANGHAI

BAR_INTERVAL = timedelta(minutes=5)
# One source publication interval is allowed, never yesterday/morning data.
# Live delay is an acceptance item, not established by historical downloads.
PUBLICATION_LAG = BAR_INTERVAL


def latest_closed_boundary(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise MinuteDataError("timezone_required")
    value = now.astimezone(SHANGHAI)
    return value.replace(minute=value.minute // 5 * 5, second=0, microsecond=0)


def fresh(cutoff: datetime, now: datetime) -> bool:
    return cutoff.date() == now.date() and latest_closed_boundary(now) - PUBLICATION_LAG <= cutoff <= now


def normalize(frame: pd.DataFrame, now: datetime, *, stock: bool = True) -> pd.DataFrame:
    required = ["trade_time", "open", "high", "low", "close", "vol"]
    if frame.empty or not set(required) <= set(frame.columns):
        raise MinuteDataError("minute_columns_missing")
    data = frame.copy()
    stamps = pd.to_datetime(data.trade_time, errors="raise")
    data["trade_time"] = stamps.dt.tz_localize(SHANGHAI) if stamps.dt.tz is None else stamps.dt.tz_convert(SHANGHAI)
    # Filter BEFORE numerical validation, features or hashing: future rows cannot
    # affect any earlier result, including normalization and invalid values.
    data = data[(data.trade_time.dt.date == now.date()) & (data.trade_time <= now) & (data.trade_time <= latest_closed_boundary(now))].copy()
    if data.empty:
        raise MinuteDataError("target_session_minutes_missing")
    stamps = data.trade_time
    if not stamps.is_monotonic_increasing or stamps.duplicated().any():
        raise MinuteDataError("minute_order_or_duplicate")
    if any(t.second or t.microsecond or t.minute % 5 or not (time(9, 35) <= t.time() <= time(11, 30) or time(13, 5) <= t.time() <= time(15)) for t in stamps):
        raise MinuteDataError("minute_timestamp_invalid")
    if "amount" in data:
        data["amount"] = pd.to_numeric(data.amount, errors="raise")
        if data.amount.isna().any():
            data = data.drop(columns="amount")
    columns = required[1:] + (["amount"] if "amount" in data else [])
    for column in columns:
        data[column] = pd.to_numeric(data[column], errors="raise")
    if not np.isfinite(data[columns].to_numpy()).all() or (data[["open", "high", "low", "close"]] <= 0).any().any() or (data.vol < 0).any():
        raise MinuteDataError("minute_values_invalid")
    if (data.high < data[["open", "close", "low"]].max(axis=1)).any() or (data.low > data[["open", "close", "high"]].min(axis=1)).any():
        raise MinuteDataError("minute_ohlc_invalid")
    if "amount" in data:
        if (data.amount < 0).any() or ((data.vol == 0) & (data.amount != 0)).any():
            raise MinuteDataError("minute_amount_invalid")
        traded = data[data.vol > 0]
        # Amount / shares must be a traded price in this bar (one tick tolerance).
        average = traded.amount / traded.vol
        if stock and ((average < traded.low - .011) | (average > traded.high + .011)).any():
            raise MinuteDataError("minute_units_or_price_basis_invalid")
    end = stamps.iloc[-1].to_pydatetime()
    if not fresh(end, now):
        raise MinuteDataError("minute_evidence_stale")
    expected = pd.date_range(end - timedelta(minutes=30), end, freq="5min")
    if tuple(stamps.tail(7)) != tuple(expected) or (data.tail(7).vol <= 0).any():
        raise MinuteDataError("recent_minutes_incomplete_or_no_trades")
    return data.reset_index(drop=True)


def build_evidence(frame, benchmark, *, candidate, now, fetched_at, request_ms, benchmark_error=None):
    data = normalize(frame, now)
    last = data.iloc[-1]
    cutoff = last.trade_time.to_pydatetime()
    limitations = []
    bench15 = bench30 = relative = None
    if benchmark is not None:
        try:
            bench = normalize(benchmark, cutoff, stock=False)
            if bench.iloc[-1].trade_time != last.trade_time:
                raise MinuteDataError("benchmark_cutoff_mismatch")
            bench15 = float(bench.iloc[-1].close / bench.iloc[-4].close - 1)
            bench30 = float(bench.iloc[-1].close / bench.iloc[-7].close - 1)
        except (MinuteDataError, ValueError) as exc:
            limitations.append(f"benchmark_unavailable:{exc}")
    else:
        limitations.append(f"benchmark_unavailable:{benchmark_error}")
    ret15 = float(last.close / data.iloc[-4].close - 1)
    ret30 = float(last.close / data.iloc[-7].close - 1)
    if bench30 is not None:
        relative = ret30 - bench30
    vwap = distance = prior_distance = None
    expected_day = list(pd.date_range(f"{now.date()} 09:35", f"{now.date()} 11:30", freq="5min", tz=SHANGHAI)) + list(pd.date_range(f"{now.date()} 13:05", cutoff.replace(tzinfo=None), freq="5min", tz=SHANGHAI))
    if "amount" in data and tuple(data.trade_time) == tuple(expected_day):
        vwap = float(data.amount.sum() / data.vol.sum())
        distance = float(last.close / vwap - 1)
        prior = data.iloc[:-3]
        prior_distance = float(prior.iloc[-1].close / (prior.amount.sum() / prior.vol.sum()) - 1)
    else:
        limitations.append("day_vwap_unavailable:amount_or_day_coverage_missing")
    trade = candidate.trade_plan
    position = "unrecorded" if trade.entry_low is None or trade.entry_high is None else "below" if last.close < trade.entry_low else "above" if last.close > trade.entry_high else "inside"
    constraints = []
    if trade.action in {"blocked", "unavailable", "suspended", "halted", "do_not_trade"}:
        constraints.append(trade.action)
    if candidate.disposition.value != "selected":
        constraints.append("not_selected_by_daily_plan")
    if trade.stop_price is None:
        constraints.append("stop_unrecorded")
    stop_breached = trade.stop_price is not None and last.close <= trade.stop_price
    rows = data[["trade_time", *[c for c in ("open", "high", "low", "close", "vol", "amount") if c in data]]].astype({"trade_time": str}).to_dict("records")
    facts = dict(source=SOURCE, symbol=candidate.symbol, cutoff=cutoff, fetched_at=fetched_at, price_basis="unadjusted_cny", last_price=float(last.close), return_15m=ret15, return_30m=ret30, closes_30m=tuple(data.close.tail(7)), highs_30m=tuple(data.high.tail(7)), lows_30m=tuple(data.low.tail(7)), volume_recent_15m_to_prior_15m=float(data.vol.tail(3).sum() / data.vol.iloc[-6:-3].sum()), vwap=vwap, price_vs_vwap=distance, price_vs_vwap_15m_ago=prior_distance, benchmark_return_15m=bench15, benchmark_return_30m=bench30, relative_return_30m=relative, entry_position=position, stop_breached=bool(stop_breached), trade_constraints=tuple(constraints), limitations=tuple(limitations), request_ms=request_ms)
    facts["return_since_open"] = float(last.close / data.iloc[0].open - 1) if data.iloc[0].trade_time.time() == time(9, 35) else None
    semantic = {k: v for k, v in facts.items() if k not in {"fetched_at", "request_ms"}}
    digest = sha256(json.dumps({"facts": semantic, "bars": rows}, sort_keys=True, default=str).encode()).hexdigest()
    return EntryEvidence(digest=digest, **facts)
