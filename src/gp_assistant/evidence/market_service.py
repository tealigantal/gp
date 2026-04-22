from __future__ import annotations

from typing import Any, Dict, Iterable, List
from pathlib import Path

import pandas as pd

from ..providers.factory import get_provider
from ..runtime.market_clock import compute_market_state
from ..selection_engine.agent import run as run_selection
from ..core.paths import data_dir
from ..core.logging import logger
from ..selection_engine.datahub import MarketDataHub


def current_trading_day() -> str:
    ms = compute_market_state()
    # For daybook computations, use target completed day
    return str(ms.target_daybook_effective_day)


def build_day_selection(trading_day: str, *, topk: int = 12, risk_profile: str = 'normal') -> Dict[str, Any]:
    date = f"{trading_day[:4]}-{trading_day[4:6]}-{trading_day[6:8]}" if len(trading_day) == 8 else trading_day
    return run_selection(date=date, topk=topk, universe='auto', risk_profile=risk_profile)


def fetch_snapshot() -> pd.DataFrame | None:
    provider = get_provider()
    try:
        return provider.get_spot_snapshot()
    except Exception:
        return None


def _infer_ts_code(symbol: str) -> str:
    s = str(symbol).strip().upper()
    if '.' in s:
        return s
    return f"{s}.SH" if s.startswith('6') else f"{s}.SZ"


def _local_min5_path(symbol: str, trading_day: str) -> Path:
    ts_code = _infer_ts_code(symbol)
    return data_dir() / 'bars' / 'min5' / f'ts_code={ts_code}' / f'date={trading_day}.parquet'


def _read_local_min5(symbol: str, trading_day: str) -> pd.DataFrame | None:
    p = _local_min5_path(symbol, trading_day)
    if not p.exists():
        return None
    try:
        return pd.read_parquet(p)
    except Exception:
        return None


def _fetch_akshare_min5(symbol: str) -> pd.DataFrame | None:
    try:
        import akshare as ak  # type: ignore
    except Exception:
        logger.warning("[5m-fetch] akshare not available; skip symbol=%s", symbol)
        return None
    s = str(symbol).strip()
    ak_symbol = ('sh' if s.startswith('6') else 'sz') + s
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=ak_symbol, period='5', adjust='')
        logger.info("[5m-fetch] akshare ok symbol=%s rows=%s", symbol, (0 if df is None else len(df)))
    except Exception as e:
        logger.warning("[5m-fetch] akshare failed symbol=%s error=%s", symbol, e)
        return None
    if df is None or df.empty:
        logger.info("[5m-fetch] akshare empty symbol=%s", symbol)
        return None
    out = pd.DataFrame()
    out['trade_time'] = pd.to_datetime(df['时间']).dt.strftime('%Y%m%d %H:%M:%S')
    out['open'] = pd.to_numeric(df['开盘'], errors='coerce')
    out['high'] = pd.to_numeric(df['最高'], errors='coerce')
    out['low'] = pd.to_numeric(df['最低'], errors='coerce')
    out['close'] = pd.to_numeric(df['收盘'], errors='coerce')
    out['vol'] = pd.to_numeric(df.get('成交量', 0.0), errors='coerce').fillna(0.0)
    out['amount'] = pd.to_numeric(df.get('成交额', 0.0), errors='coerce').fillna(0.0)
    return out.dropna(subset=['trade_time', 'open', 'high', 'low', 'close'])


def fetch_minute_bars_5m(symbols: Iterable[str], trading_day: str) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    total = 0
    for symbol in symbols:
        sym = str(symbol).strip()
        if not sym:
            continue
        df = _read_local_min5(sym, trading_day)
        if df is None or df.empty:
            df = _fetch_akshare_min5(sym)
        if df is None or df.empty:
            logger.info("[5m-fetch] no data symbol=%s day=%s", sym, trading_day)
            continue
        if 'trade_time' not in df.columns:
            continue
        sdf = df.copy()
        sdf['trade_time'] = pd.to_datetime(sdf['trade_time'])
        # Strictly select the requested trading day to avoid stale intraday bars
        mask = sdf['trade_time'].dt.strftime('%Y%m%d') == trading_day
        sdf = sdf.loc[mask].sort_values('trade_time').reset_index(drop=True)
        if not sdf.empty:
            out[sym] = sdf
            total += 1
            try:
                last = sdf['trade_time'].iloc[-1]
            except Exception:
                last = None
            logger.info("[5m-fetch] accepted symbol=%s bars=%d last=%s", sym, len(sdf), last)
    logger.info("[5m-fetch] summary day=%s symbols_in=%d symbols_ok=%d", trading_day, len(list(symbols)), len(out))
    return out


def probe_daybook_ready(target_day: str) -> dict:
    """Heuristic probe for EOD readiness of the given trading day.

    Query a few liquid symbols' daily bars; if at least two symbols contain the
    target_day row, consider ready. This is a conservative check to avoid publishing
    against incomplete EOD.
    """
    hub = MarketDataHub()
    symbols = ['000001', '600000', '600519']
    ok = 0
    checks: list[dict] = []
    for s in symbols:
        try:
            df, _ = hub.daily_ohlcv(s, as_of=target_day)
            last = None
            if df is not None and len(df) > 0:
                # normalize last date
                if 'date' in df.columns:
                    last = str(pd.to_datetime(df.iloc[-1]['date']).strftime('%Y%m%d'))
            ready = (last == target_day)
            ok += 1 if ready else 0
            checks.append({'symbol': s, 'last': last, 'ready': ready, 'len': int(len(df) if df is not None else 0)})
        except Exception as e:
            checks.append({'symbol': s, 'error': str(e)})
    ready = ok >= 2
    return {'ready': ready, 'ok_count': ok, 'target_day': target_day, 'checks': checks}
