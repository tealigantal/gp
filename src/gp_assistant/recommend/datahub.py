# 简介：行情数据枢纽（严格模式）。仅返回真实数据（或本地夹带 fixtures），
# 不做合成降级；缺失即抛错，由上层决定是否中止。
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
import requests

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
        # Optional offline fixtures under store/fixtures/bars/<symbol>.csv
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
        # fixtures -> provider; no synthetic fallback
        cfg = load_config()
        df: Optional[pd.DataFrame] = None if cfg.strict_real_data else self._from_fixtures(symbol)
        meta: Dict[str, Any] = {"source": None}
        if df is not None:
            meta["source"] = "fixtures"
        else:
            provider = get_provider()
            raw = provider.get_daily(symbol, start=None, end=as_of)
            df = raw
            meta["source"] = f"provider:{provider.name}"
        if df is None or len(df) == 0:
            raise ValueError(f"daily_ohlcv: 无法获取真实数据 symbol={symbol}")
        df_norm, m = normalize_daily_ohlcv(df)
        meta.update(m)
        meta["len"] = len(df_norm)
        meta["insufficient_history"] = len(df_norm) < min_len
        df_norm.attrs.update(meta)
        return df_norm, meta

    def index_daily(self, symbol: str) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Fetch index daily bars via akshare real index API (no synthetic)."""
        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"akshare 未安装或导入失败: {e}")
        sym = symbol.strip().lower()
        # Accept forms: 000300 -> sh000300; 399006 -> sz399006
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
        # Normalize columns to OHLCV-like
        rename = {
            "date": "date" if "date" in df.columns else None,
            "open": "open" if "open" in df.columns else None,
            "high": "high" if "high" in df.columns else None,
            "low": "low" if "low" in df.columns else None,
            "close": "close" if "close" in df.columns else None,
            "volume": "volume" if "volume" in df.columns else None,
        }
        # AkShare already uses standard names; ensure amount exists for downstream
        import pandas as pd
        out = df.copy()
        if "amount" not in out.columns:
            vwap = (out["high"] + out["low"] + out["close"]) / 3.0
            out["amount"] = vwap * out.get("volume", 0).astype(float)
        out["date"] = pd.to_datetime(out["date"]) if "date" in out.columns else pd.to_datetime(out.index)
        out = out[["date", "open", "high", "low", "close", "volume", "amount"]]
        out = out.dropna().reset_index(drop=True)
        meta = {"source": "akshare:index", "len": len(out), "insufficient_history": len(out) < 120}
        return out, meta

    def market_stats(self) -> Dict[str, Any]:
        """Compute basic market stats from real-time snapshot (no synthetic).

        Returns keys:
        - total_amount: float | None (单位以数据源为准)
        - limit_up: int | None (以涨跌幅阈值近似)
        - limit_down: int | None
        - seal_rate: None (缺失，需接深度盘口数据)
        - ladder_max: None
        - ladder_breaks: None
        - missing: list[str] 说明哪些字段缺失
        """
        from ..providers.factory import get_provider

        p = get_provider()
        snap = p.get_spot_snapshot()
        cols = set(snap.columns)
        missing: list[str] = []

        # total amount
        amount_col = None
        for c in ("成交额", "amount", "成交额(万)", "成交额(亿)"):
            if c in cols:
                amount_col = c
                break
        total_amount = None
        if amount_col:
            import pandas as pd
            try:
                s = pd.to_numeric(snap[amount_col], errors="coerce")
                total_amount = float(s.fillna(0).sum())
            except Exception:
                total_amount = None
        else:
            missing.append("total_amount")

        # change pct
        chg_col = None
        for c in ("涨跌幅", "涨跌幅(%)", "pct_chg", "涨跌", "changePct"):
            if c in cols:
                chg_col = c
                break
        limit_up = None
        limit_down = None
        if chg_col:
            import pandas as pd
            try:
                s = snap[chg_col].astype(str).str.rstrip("% ")
                s = pd.to_numeric(s, errors="coerce")
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
