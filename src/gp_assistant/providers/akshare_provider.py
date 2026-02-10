"""AkShare provider (UTF-8 normalized, no logic changes beyond cleanup).

This module exposes AkShareProvider which fetches daily OHLCV and spot snapshots.
Spot snapshot uses a single-call policy from agent; here we provide routing,
in-process TTL cache, disk cache, and circuit breaker, but do not print any
degradation logs (agent is the single authority to report degradation).
"""

from __future__ import annotations

from typing import Dict, Any, Optional
import time
import json
import pandas as pd

from ..core.errors import DataProviderError
from .base import MarketDataProvider
from ..core.paths import store_dir


class AkShareProvider(MarketDataProvider):
    name = "akshare"

    def __init__(self, timeout_sec: int = 60):
        self.timeout_sec = timeout_sec
        self._last_snapshot_meta: Dict[str, Any] = {}
        self._snapshot_cache_df: Optional[pd.DataFrame] = None
        self._snapshot_cache_ts: Optional[float] = None
        if not hasattr(AkShareProvider, "_circuit"):
            AkShareProvider._circuit = {}

    # ---- AkShare import -----------------------------------------------------
    def _import(self):  # late import to avoid hard dependency at import time
        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise DataProviderError(f"AkShare import failed: {e}") from e
        return ak

    # ---- Daily bars ---------------------------------------------------------
    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:  # noqa: D401
        """Fetch daily kline using AkShare stock_zh_a_hist (no logic changes)."""
        ak = self._import()
        s = start.replace("-", "") if start else None
        e = end.replace("-", "") if end else None
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, start_date=s, end_date=e, period="daily", adjust="")
        except Exception as ex:  # noqa: BLE001
            raise DataProviderError("AkShare get_daily failed", symbol=symbol) from ex
        if df is None or len(df) == 0:
            raise DataProviderError("AkShare daily empty", symbol=symbol)
        # Light normalization (do not alter downstream expectations)
        rename_map = {
            "日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close",
            "成交量": "volume", "vol": "volume",
        }
        for k, v in rename_map.items():
            if k in df.columns and v not in df.columns:
                df[v] = df[k]
        required = ["date", "open", "high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise DataProviderError(f"AkShare daily missing columns: {missing}", symbol=symbol)
        return df

    def healthcheck(self) -> Dict[str, Any]:
        try:
            self._import()
            return {"name": self.name, "ok": True, "reason": None}
        except Exception as e:  # noqa: BLE001
            return {"name": self.name, "ok": False, "reason": str(e)}

    # ---- Basic listing ------------------------------------------------------
    def get_stock_basic(self):  # noqa: ANN001
        ak = self._import()
        try:
            df = self._call_with_retry(lambda: self._with_requests_timeout(lambda: ak.stock_zh_a_spot_em()), retries=1)
            res = pd.DataFrame({"ts_code": df.get("代码"), "name": df.get("名称")})
            return res
        except Exception as e:  # noqa: BLE001
            raise DataProviderError(f"AkShare basic failed: {e}")

    # ---- Spot snapshot (single-call policy) --------------------------------
    def get_spot_snapshot(self):  # noqa: ANN001
        ak = self._import()
        t0 = time.time()
        em_err: Exception | None = None
        skipped: list[str] = []
        # Memory TTL cache (<=120s)
        try:
            if self._snapshot_cache_df is not None and self._snapshot_cache_ts is not None:
                if (time.time() - self._snapshot_cache_ts) <= 120:
                    self._last_snapshot_meta = {
                        "source": "memory_cache",
                        "cache": "memory",
                        "fallback": False,
                        "stale": False,
                        "missing": False,
                        "elapsed_sec": 0.0,
                        "skipped_routes": [],
                    }
                    return self._snapshot_cache_df
        except Exception:
            pass
        # Direct EM route (large page size, polite headers)
        try:
            if self._cb_should_skip("em:direct"):
                skipped.append("em:direct")
                raise RuntimeError("circuit_open_em_direct")
            df_direct = self._em_spot_direct()
            if df_direct is not None and len(df_direct) > 0:
                self._last_snapshot_meta = {
                    "source": "em:direct",
                    "fallback": False,
                    "stale": False,
                    "missing": False,
                    "elapsed_sec": round(time.time() - t0, 2),
                    "skipped_routes": skipped,
                }
                self._update_snapshot_cache(df_direct)
                self._save_snapshot_disk(df_direct)
                self._cb_report_success("em:direct")
                return df_direct
        except Exception as e:  # noqa: BLE001
            em_err = e
            if "circuit_open" not in str(e):
                self._cb_report_failure("em:direct", e)
        # AkShare EM
        try:
            if self._cb_should_skip("akshare:em"):
                skipped.append("akshare:em")
                raise RuntimeError("circuit_open_ak_em")
            df = self._call_with_retry(lambda: self._with_requests_timeout(lambda: ak.stock_zh_a_spot_em()), retries=1)
            if df is None or len(df) == 0:
                raise DataProviderError("AkShare EM snapshot empty")
            self._last_snapshot_meta = {
                "source": "akshare:em",
                "fallback": False,
                "stale": False,
                "missing": False,
                "elapsed_sec": round(time.time() - t0, 2),
                "skipped_routes": skipped,
            }
            self._update_snapshot_cache(df)
            self._save_snapshot_disk(df)
            self._cb_report_success("akshare:em")
            return df
        except Exception as e:  # noqa: BLE001
            em_err = e
            if "circuit_open" not in str(e):
                self._cb_report_failure("akshare:em", e)
        # Sina fallback
        try:
            if self._cb_should_skip("akshare:sina"):
                skipped.append("akshare:sina")
                raise RuntimeError("circuit_open_ak_sina")
            df = self._call_with_retry(lambda: self._with_requests_timeout(lambda: ak.stock_zh_a_spot()))
            if df is None or len(df) == 0:
                raise DataProviderError("AkShare Sina snapshot empty")
            self._last_snapshot_meta = {
                "source": "akshare:sina",
                "fallback": True,
                "fallback_reason": f"em_failed: {em_err}",
                "stale": False,
                "missing": False,
                "elapsed_sec": round(time.time() - t0, 2),
                "skipped_routes": skipped,
            }
            self._update_snapshot_cache(df)
            self._save_snapshot_disk(df)
            self._cb_report_success("akshare:sina")
            return df
        except Exception as e2:  # noqa: BLE001
            # Disk cache (<=24h)
            disk = self._load_snapshot_disk(max_age_sec=24 * 3600)
            if disk is not None:
                age = float(disk[1])
                df_disk = disk[0]
                self._last_snapshot_meta = {
                    "source": "disk_cache",
                    "cache": "disk",
                    "fallback": True,
                    "fallback_reason": f"live_failed: {em_err or e2}",
                    "stale": True,
                    "missing": False,
                    "cache_age_sec": age,
                    "skipped_routes": skipped,
                }
                self._update_snapshot_cache(df_disk)
                return df_disk
            raise DataProviderError(f"AkShare snapshot failed: {em_err or e2}")

    def last_snapshot_meta(self) -> Dict[str, Any]:
        # Always include keys useful for structured decisions
        base = {
            "source": None,
            "cache": None,
            "fallback": False,
            "fallback_reason": None,
            "stale": False,
            "missing": False,
            "elapsed_sec": None,
            "cache_age_sec": None,
            "skipped_routes": [],
        }
        base.update(self._last_snapshot_meta or {})
        if base.get("skipped_routes") is None:
            base["skipped_routes"] = []
        return base

    # ---- Internals: request patch + retry ----------------------------------
    def _with_requests_timeout(self, fn):  # noqa: ANN001
        import requests  # type: ignore
        original = requests.sessions.Session.request

        def wrapped(session, method, url, **kwargs):  # noqa: ANN001
            to = kwargs.get("timeout", None)
            if to is None or (isinstance(to, (int, float)) and to < self.timeout_sec):
                kwargs["timeout"] = self.timeout_sec
            try:
                hdrs = dict(kwargs.get("headers") or {})
                hdrs.setdefault("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36")
                if isinstance(url, str):
                    if "eastmoney.com" in url:
                        hdrs.setdefault("Referer", "https://quote.eastmoney.com/")
                    elif "sina.com" in url or "sinajs.cn" in url:
                        hdrs.setdefault("Referer", "https://finance.sina.com.cn/")
                kwargs["headers"] = hdrs
            except Exception:
                pass
            return original(session, method, url, **kwargs)

        try:
            requests.sessions.Session.request = wrapped  # type: ignore
            return fn()
        finally:
            requests.sessions.Session.request = original  # type: ignore

    def _call_with_retry(self, fn, retries: int = 3):  # noqa: ANN001
        import random
        for i in range(retries):
            try:
                return fn()
            except Exception as e:  # noqa: BLE001
                if i == retries - 1:
                    raise e
                time.sleep((2 ** i) + random.random() * 0.5)

    # ---- Direct EM snapshot -------------------------------------------------
    def _em_spot_direct(self):  # noqa: ANN001
        import requests

        url = "https://push2.eastmoney.com/api/qt/clist/get"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
            "Accept": "application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        page = 1
        page_size = 5000
        out = []
        total = None
        for _ in range(5):
            params = {
                "pn": str(page), "pz": str(page_size), "po": "1", "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
                "fid": "f12",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152",
            }
            def _do():
                s = requests.Session()
                return s.get(url, params=params, headers=headers, timeout=self.timeout_sec)
            resp = self._with_requests_timeout(_do)
            data = resp.json()
            diff = data.get("data", {}).get("diff", [])
            if not diff:
                break
            out.extend(diff)
            total = data.get("data", {}).get("total", None)
            if total is None or len(out) >= int(total):
                break
            page += 1
        if not out:
            return None
        df = pd.DataFrame(out)
        rename = {"f12": "代码", "f14": "名称", "f2": "最新价", "f3": "涨跌幅", "f6": "成交额"}
        df = df.rename(columns=rename)
        keep = [c for c in ["代码", "名称", "最新价", "涨跌幅", "成交额"] if c in df.columns]
        df = df[keep]
        return df

