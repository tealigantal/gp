from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, time
from hashlib import sha256
import json
import math
import multiprocessing
from queue import Empty
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from ..contracts.decision import CandidateDecision
from ..contracts.evidence import ExpertContribution


BENCHMARK_SYMBOL = "000300"
LUNCH_SOURCE = "akshare:sina:5m"
LUNCH_POLICY_REVISION = "lunch_5m_direct_rerank_v1"
_COLUMNS = ("trade_time", "open", "high", "low", "close", "vol", "amount")


class LunchBatchUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LunchSignal:
    score: float
    vwap_proxy: float
    relative_return: float
    price_vs_vwap: float
    close_location: float
    last_hour_return: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class LunchFiveMinuteBatch:
    market_session_date: date
    slot_closed_at: datetime
    source: str
    content_digest: str
    bars: dict[str, pd.DataFrame]
    benchmark: pd.DataFrame
    signals: dict[str, LunchSignal]


def _expected_times(session_date: date) -> tuple[pd.Timestamp, ...]:
    return tuple(pd.date_range(f"{session_date.isoformat()} 09:35:00", f"{session_date.isoformat()} 11:30:00", freq="5min"))


def _normalize_exact_bars(frame: pd.DataFrame, *, session_date: date, symbol: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise LunchBatchUnavailable(f"minute_bars_missing:{symbol}")
    missing = [column for column in _COLUMNS if column not in frame.columns]
    if missing:
        raise LunchBatchUnavailable(f"minute_columns_missing:{symbol}")
    normalized = frame.loc[:, _COLUMNS].copy()
    normalized["trade_time"] = pd.to_datetime(normalized["trade_time"], errors="coerce")
    for column in _COLUMNS[1:]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    if normalized.isna().any().any():
        raise LunchBatchUnavailable(f"minute_values_invalid:{symbol}")
    observed_times = tuple(normalized["trade_time"])
    if observed_times != _expected_times(session_date):
        raise LunchBatchUnavailable(f"minute_window_incomplete:{symbol}")
    numeric_values = normalized.loc[:, _COLUMNS[1:]].to_numpy().ravel()
    if any(not math.isfinite(float(value)) for value in numeric_values):
        raise LunchBatchUnavailable(f"minute_values_non_finite:{symbol}")
    if (normalized[["open", "high", "low", "close"]] <= 0).any().any():
        raise LunchBatchUnavailable(f"minute_price_invalid:{symbol}")
    if (normalized[["vol", "amount"]] < 0).any().any() or float(normalized["vol"].sum()) <= 0:
        raise LunchBatchUnavailable(f"minute_volume_invalid:{symbol}")
    if (
        (normalized["high"] < normalized[["open", "close"]].max(axis=1)).any()
        or (normalized["low"] > normalized[["open", "close"]].min(axis=1)).any()
        or (normalized["high"] < normalized["low"]).any()
    ):
        raise LunchBatchUnavailable(f"minute_ohlc_invalid:{symbol}")
    return normalized.reset_index(drop=True)


def _canonical_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        rows.append(
            {
                "trade_time": pd.Timestamp(row.trade_time).isoformat(),
                "open": round(float(row.open), 8),
                "high": round(float(row.high), 8),
                "low": round(float(row.low), 8),
                "close": round(float(row.close), 8),
                "vol": round(float(row.vol), 8),
                "amount": round(float(row.amount), 8),
            }
        )
    return rows


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _signal(frame: pd.DataFrame, benchmark: pd.DataFrame) -> LunchSignal:
    first_open = float(frame.iloc[0]["open"])
    close = float(frame.iloc[-1]["close"])
    benchmark_return = float(benchmark.iloc[-1]["close"]) / float(benchmark.iloc[0]["open"]) - 1.0
    morning_return = close / first_open - 1.0
    relative_return = morning_return - benchmark_return
    total_volume = float(frame["vol"].sum())
    vwap_proxy = float((frame["close"] * frame["vol"]).sum()) / total_volume
    price_vs_vwap = close / vwap_proxy - 1.0
    morning_low = float(frame["low"].min())
    morning_high = float(frame["high"].max())
    close_location = 0.5 if morning_high <= morning_low else (close - morning_low) / (morning_high - morning_low)
    last_hour_open = float(frame.tail(12).iloc[0]["open"])
    last_hour_return = close / last_hour_open - 1.0
    score = (
        0.45 * _clip01((relative_return + 0.04) / 0.08)
        + 0.30 * _clip01((price_vs_vwap + 0.02) / 0.04)
        + 0.15 * _clip01(close_location)
        + 0.10 * _clip01((last_hour_return + 0.025) / 0.05)
    )
    reasons = (
        "lunch_relative_strength_positive" if relative_return >= 0 else "lunch_relative_strength_negative",
        "lunch_above_volume_price_proxy" if price_vs_vwap >= 0 else "lunch_below_volume_price_proxy",
        "lunch_close_location_strong" if close_location >= 0.6 else "lunch_close_location_weak" if close_location <= 0.4 else "lunch_close_location_mid",
        "lunch_last_hour_positive" if last_hour_return >= 0 else "lunch_last_hour_negative",
    )
    return LunchSignal(
        score=round(_clip01(score), 12),
        vwap_proxy=round(vwap_proxy, 8),
        relative_return=round(relative_return, 12),
        price_vs_vwap=round(price_vs_vwap, 12),
        close_location=round(_clip01(close_location), 12),
        last_hour_return=round(last_hour_return, 12),
        reason_codes=reasons,
    )


def collect_lunch_batch(
    provider,
    symbols: Iterable[str],
    *,
    market_session_date: date,
    timezone,
    max_workers: int = 3,
) -> LunchFiveMinuteBatch:
    clean_symbols = tuple(sorted(dict.fromkeys(str(symbol).zfill(6) for symbol in symbols)))
    if len(clean_symbols) != 30:
        raise LunchBatchUnavailable("lunch_top30_scope_invalid")
    start = f"{market_session_date.isoformat()} 09:35:00"
    end = f"{market_session_date.isoformat()} 11:30:00"

    def fetch(symbol: str) -> tuple[str, pd.DataFrame]:
        if symbol == BENCHMARK_SYMBOL:
            frame = provider.get_index_minute_bars_5m(symbol, start, end, allow_fallback=False)
        else:
            frame = provider.get_minute_bars_5m(symbol, start, end, allow_fallback=False)
        return symbol, _normalize_exact_bars(frame, session_date=market_session_date, symbol=symbol)

    fetched: dict[str, pd.DataFrame] = {}
    requested = (*clean_symbols, BENCHMARK_SYMBOL)
    try:
        with ThreadPoolExecutor(max_workers=max(1, min(3, int(max_workers)))) as executor:
            futures = {executor.submit(fetch, symbol): symbol for symbol in requested}
            for future in as_completed(futures):
                symbol, frame = future.result()
                fetched[symbol] = frame
    except Exception as exc:
        if isinstance(exc, LunchBatchUnavailable):
            raise
        raise LunchBatchUnavailable(f"lunch_source_failed:{type(exc).__name__}") from exc
    if set(fetched) != set(requested):
        raise LunchBatchUnavailable("lunch_batch_incomplete")
    benchmark = fetched.pop(BENCHMARK_SYMBOL)
    payload = {
        "policy_revision": LUNCH_POLICY_REVISION,
        "source": LUNCH_SOURCE,
        "market_session_date": market_session_date.isoformat(),
        "benchmark": {"symbol": BENCHMARK_SYMBOL, "bars": _canonical_rows(benchmark)},
        "symbols": {symbol: _canonical_rows(fetched[symbol]) for symbol in clean_symbols},
    }
    digest = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    signals = {symbol: _signal(frame, benchmark) for symbol, frame in fetched.items()}
    return LunchFiveMinuteBatch(
        market_session_date=market_session_date,
        slot_closed_at=datetime.combine(market_session_date, time(11, 30), tzinfo=timezone),
        source=LUNCH_SOURCE,
        content_digest=digest,
        bars=fetched,
        benchmark=benchmark,
        signals=signals,
    )


def _collect_lunch_batch_child(queue, symbols: tuple[str, ...], session_iso: str, timezone_name: str) -> None:
    try:
        from ..providers.factory import get_provider

        batch = collect_lunch_batch(
            get_provider(prefer="akshare"),
            symbols,
            market_session_date=date.fromisoformat(session_iso),
            timezone=ZoneInfo(timezone_name),
            max_workers=3,
        )
        queue.put(("ok", batch))
    except Exception as exc:  # noqa: BLE001
        queue.put(("error", f"{type(exc).__name__}:{exc}"))


def collect_lunch_batch_isolated(
    symbols: Iterable[str],
    *,
    market_session_date: date,
    timezone_name: str,
    budget_sec: int,
) -> LunchFiveMinuteBatch:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_collect_lunch_batch_child,
        args=(queue, tuple(symbols), market_session_date.isoformat(), timezone_name),
        name="gp-lunch-minute-collector",
        daemon=False,
    )
    process.start()
    try:
        state, payload = queue.get(timeout=max(5, int(budget_sec)))
    except Empty as exc:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        raise LunchBatchUnavailable("lunch_collection_budget_exceeded") from exc
    finally:
        queue.close()
    process.join(timeout=5)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    if state != "ok":
        raise LunchBatchUnavailable(str(payload))
    return payload


def rerank_lunch_candidates(
    candidates: tuple[CandidateDecision, ...],
    *,
    eligible_symbols: frozenset[str],
    batch: LunchFiveMinuteBatch,
) -> tuple[CandidateDecision, ...]:
    if eligible_symbols != frozenset(batch.signals):
        raise LunchBatchUnavailable("lunch_signal_scope_mismatch")
    reranked: list[CandidateDecision] = []
    for candidate in candidates:
        if candidate.symbol not in eligible_symbols:
            reranked.append(candidate)
            continue
        signal = batch.signals[candidate.symbol]
        serenity_contribution = sum(
            float(expert.contribution)
            for expert in candidate.experts
            if expert.expert == "serenity" and float(expert.weight) == 0.03
        )
        serenity_contribution = max(-0.03, min(0.03, serenity_contribution))
        final_score = _clip01(signal.score + serenity_contribution)
        intraday_expert = ExpertContribution(
            expert="intraday_5m",
            contribution=round(final_score - float(candidate.adaptive_score), 12),
            weight=1.0,
            reason_codes=signal.reason_codes,
        )
        reranked.append(
            candidate.model_copy(
                update={
                    "adaptive_score": round(final_score, 12),
                    "experts": (*candidate.experts, intraday_expert),
                }
            )
        )
    return tuple(reranked)
