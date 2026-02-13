# 简介：行情数据枢纽（严格模式）。仅返回真实数据（或本地 fixtures），不做合成降级。
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from ..core.paths import store_dir
from ..core.config import load_config
from ..providers.factory import get_provider
from ..tools.market_data import normalize_daily_ohlcv


def _cache_path(kind: str, key: str) -> Path:
    p = store_dir() / "cache" / kind
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.json"


def _save_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


@dataclass
class MarketDataHub:
    """Multi-source market data with caching and unified schema."""

    timeout: int = 15

    def _from_fixtures(self, symbol: str) -> Optional[pd.DataFrame]:
        root = store_dir() / "fixtures" / "bars"
        for suffix in [".csv", ".parquet", ".json"]:
            fp = root / f"{symbol}{suffix}"
            if fp.exists():
                try:
                    if suffix == ".csv":
                        df = pd.read_csv(fp)
                    elif suffix == ".parquet":
                        df = pd.read_parquet(fp)
                    else:
                        df = pd.DataFrame(json.loads(fp.read_text(encoding="utf-8")))
                    return df
                except Exception:
                    continue
        return None

    def daily_ohlcv(self, symbol: str, as_of: Optional[str] = None, min_len: int = 250) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        cfg = load_config()
        df: Optional[pd.DataFrame] = None if cfg.strict_real_data else self._from_fixtures(symbol)
        meta: Dict[str, Any] = {"source": None}
        if df is not None:
            meta["source"] = "fixtures"
        else:
            provider = get_provider()
            raw = provider.get_daily(symbol, start=None, end=as_of)
            df = raw
            src = getattr(provider, "_last_daily_source", None)
            meta["source"] = src or f"provider:{provider.name}"
            try:
                atts = getattr(provider, "_last_daily_attempts", None)
                if atts is not None:
                    meta["attempts"] = atts
            except Exception:
                pass
        if df is None or len(df) == 0:
            raise ValueError(f"daily_ohlcv: 无法获取真实数据 symbol={symbol}")
        df_norm, m = normalize_daily_ohlcv(df)
        meta.update(m)
        meta["len"] = len(df_norm)
        meta["insufficient_history"] = len(df_norm) < min_len
        df_norm.attrs.update(meta)
        return df_norm, meta

    def index_daily(self, symbol: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"akshare 未安装或导入失败: {e}")
        sym = symbol.strip().lower()
        if sym.startswith("0"):
            sym = "sh" + sym
        elif sym.startswith("3") or sym.startswith("399"):
            if not sym.startswith("sz"):
                sym = "sz" + sym
        try:
            df = ak.stock_zh_index_daily(symbol=sym)  # type: ignore[attr-defined]
        except Exception as ex:  # noqa: BLE001
            raise RuntimeError(f"获取指数日线失败: {symbol}: {ex}")
        if df is None or len(df) == 0:
            raise RuntimeError(f"指数日线为空: {symbol}")
        out = df.copy()
        if "amount" not in out.columns:
            vwap = (out["high"] + out["low"] + out["close"]) / 3.0
            out["amount"] = vwap * out.get("volume", 0).astype(float)
        out["date"] = pd.to_datetime(out["date"]) if "date" in out.columns else pd.to_datetime(out.index)
        out = out[["date", "open", "high", "low", "close", "volume", "amount"]]
        out = out.dropna().reset_index(drop=True)
        meta = {"source": "akshare:index", "len": len(out), "insufficient_history": len(out) < 120}
        return out, meta

    def market_stats(self, snapshot: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        if snapshot is None:
            return {
                "total_amount": None,
                "limit_up": None,
                "limit_down": None,
                "seal_rate": None,
                "ladder_max": None,
                "ladder_breaks": None,
                "missing": ["snapshot_unavailable"],
                "source": "snapshot",
            }
        snap = snapshot
        # Canonical aliases for amount / pct_chg
        def _norm(s: str) -> str:
            x = (s or "").strip().lower()
            x = x.replace("（", "(").replace("）", ")").replace("％", "%").replace("%", "")
            x = "".join(x.split())
            return x
        def _pick(df, cands):
            cmap = { _norm(c): c for c in df.columns }
            for k in cands:
                nk = _norm(k)
                if nk in cmap:
                    return cmap[nk]
            return None
        amt_src = _pick(snap, ["成交额", "成交金额", "amount", "turnover", "成交额(元)"])
        if amt_src and "amount" not in snap.columns:
            snap = snap.copy(); snap["amount"] = snap[amt_src]
        chg_src = _pick(snap, ["涨跌幅", "涨跌幅(%)", "涨跌", "pct_chg", "changepct", "change_pct", "pct_change"])
        if chg_src and "pct_chg" not in snap.columns:
            snap = snap.copy(); snap["pct_chg"] = snap[chg_src]

        missing: list[str] = []
        # total amount
        total_amount = None
        if "amount" in snap.columns:
            try:
                s = pd.to_numeric(snap["amount"], errors="coerce")
                total_amount = float(s.fillna(0).sum())
            except Exception:
                total_amount = None
        else:
            missing.append("total_amount")

        # change pct / limits
        limit_up = None
        limit_down = None
        if "pct_chg" in snap.columns:
            try:
                s = pd.to_numeric((snap["pct_chg"].astype(str).str.rstrip("% ")), errors="coerce")
                # 量纲修正：小数 -> 百分比
                try:
                    median_abs = float(s.abs().median()) if not s.abs().isna().all() else None
                    max_abs = float(s.abs().max()) if not s.abs().isna().all() else None
                    if median_abs is not None and max_abs is not None and median_abs < 1 and max_abs <= 1.0:
                        s = s * 100.0
                except Exception:
                    pass
                limit_up = int((s >= 9.5).sum())
                limit_down = int((s <= -9.5).sum())
            except Exception:
                missing.extend(["limit_up", "limit_down"])
        else:
            missing.extend(["limit_up", "limit_down"])

        return {
            "total_amount": total_amount,
            "limit_up": limit_up,
            "limit_down": limit_down,
            "seal_rate": None,
            "ladder_max": None,
            "ladder_breaks": None,
            "missing": missing,
            "source": "snapshot",
        }
