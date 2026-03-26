from __future__ import annotations

from typing import Dict, Iterable, List

import pandas as pd

from ..contracts.objects import MarketBook, SymbolPulse, AdvicePick
from ..evidence.market_service import fetch_minute_bars_5m
from ..runtime.utils import now_iso


def _extract_price(levels: dict, keys: list[str]) -> float | None:
    for k in keys:
        v = levels.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except Exception:
            continue
    return None


def _pulse_from_df(symbol: str, pick: AdvicePick | None, df: pd.DataFrame) -> SymbolPulse:
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last
    last_close = float(last['close'])
    prev_close = float(prev['close']) if float(prev['close']) else last_close
    ret1 = 0.0 if prev_close == 0 else (last_close / prev_close - 1.0)
    recent_vol = pd.to_numeric(df['vol'].tail(12), errors='coerce').fillna(0.0)
    vol_rel = float(recent_vol.iloc[-1] / max(recent_vol.median(), 1e-6)) if not recent_vol.empty else 1.0
    entry_ref = None
    stop_ref = None
    if pick is not None:
        entry_ref = _extract_price(pick.entry_plan, ['mid', 'price', 'entry', 'anchor', 'buy'])
        stop_ref = _extract_price(pick.stop_plan, ['price', 'stop', 'invalid', 'invalidation'])
    entry_distance = None if entry_ref in (None, 0) else (last_close / float(entry_ref) - 1.0)
    invalidated = bool(stop_ref not in (None, 0) and last_close < float(stop_ref))
    if invalidated:
        state = 'invalidated'
    elif entry_distance is not None and entry_distance > 0.03:
        state = 'extended'
    elif entry_distance is not None and -0.02 <= entry_distance <= 0.015 and ret1 > -0.01:
        state = 'actionable'
    else:
        state = 'observe'
    pulse_score = max(-1.5, min(1.5, 3.0 * ret1 + 0.15 * (vol_rel - 1.0)))
    momentum = 'up' if ret1 > 0.003 else ('down' if ret1 < -0.003 else 'flat')
    stretch = 'high' if (entry_distance is not None and entry_distance > 0.03) else 'normal'
    liquidity = 'good' if vol_rel >= 0.8 else 'thin'
    return SymbolPulse(
        symbol=symbol,
        last_bar_at=str(pd.to_datetime(last['trade_time']).to_pydatetime().isoformat()),
        pulse_score=float(pulse_score),
        momentum_state=momentum,
        stretch_state=stretch,
        liquidity_state=liquidity,
        execution_state=state,
        invalidated=invalidated,
        entry_distance_pct=(None if entry_distance is None else float(entry_distance)),
        flags=[f'vol_rel={vol_rel:.2f}', f'ret1={ret1:.4f}'],
        evidence_refs=[symbol],
    )


def apply_pulse(book: MarketBook, symbols: Iterable[str]) -> MarketBook:
    bars = fetch_minute_bars_5m(symbols, book.trading_day)
    pick_map = {p.symbol: p for p in book.daybook.picks}
    for symbol, df in bars.items():
        if df is None or df.empty:
            continue
        book.symbol_states[symbol] = _pulse_from_df(symbol, pick_map.get(symbol), df)
        book.last_closed_5m = book.symbol_states[symbol].last_bar_at or book.last_closed_5m
    book.updated_at = now_iso()
    return book
