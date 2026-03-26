from __future__ import annotations

from typing import Any, Dict, Iterable, List
from pathlib import Path

import pandas as pd

from ..providers.factory import get_provider
from ..selection_engine.calendar import calendar_summary
from ..selection_engine.agent import run as run_selection
from ..core.paths import data_dir


def current_trading_day() -> str:
    cal = calendar_summary()
    as_of = str(cal.get('as_of') or '')
    return as_of.replace('-', '') if '-' in as_of else as_of


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
        return None
    s = str(symbol).strip()
    ak_symbol = ('sh' if s.startswith('6') else 'sz') + s
    try:
        df = ak.stock_zh_a_hist_min_em(symbol=ak_symbol, period='5', adjust='')
    except Exception:
        return None
    if df is None or df.empty:
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
    for symbol in symbols:
        sym = str(symbol).strip()
        if not sym:
            continue
        df = _read_local_min5(sym, trading_day)
        if df is None or df.empty:
            df = _fetch_akshare_min5(sym)
        if df is None or df.empty:
            continue
        if 'trade_time' not in df.columns:
            continue
        sdf = df.copy()
        sdf['trade_time'] = pd.to_datetime(sdf['trade_time'])
        mask = sdf['trade_time'].dt.strftime('%Y%m%d') == trading_day
        sdf = sdf.loc[mask].sort_values('trade_time').reset_index(drop=True)
        if not sdf.empty:
            out[sym] = sdf
    return out
