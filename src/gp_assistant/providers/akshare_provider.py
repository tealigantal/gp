"""AkShare provider with robust routing and clean snapshot metadata.

This module provides:
- Spot snapshot with priority routing (sina -> em) and strict, traceable meta
- Daily bars with multi-route fallback (tx -> sina -> em) and STRICT_REAL_DATA guard

No new dependencies are introduced; API signatures are preserved.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
import time
import pandas as pd

from ..core.errors import DataProviderError
from .base import MarketDataProvider
from ..core.config import load_config


class AkShareProvider(MarketDataProvider):
    name = "akshare"

    # Source constants (single place truth)
    SRC_SINA = "akshare:sina"
    SRC_EM = "akshare:em"
    SRC_CACHE = "cache:memory"

    def __init__(self, timeout_sec: int = 60):
        self.timeout_sec = timeout_sec
        self._last_snapshot_meta: Dict[str, Any] = {}
        self._snapshot_cache_df: Optional[pd.DataFrame] = None
        self._snapshot_cache_ts: Optional[float] = None
        self._snapshot_cache_source: Optional[str] = None
        self._last_daily_source: Optional[str] = None
        self._last_daily_attempts: Optional[list[dict]] = None

    # ---- AkShare import -----------------------------------------------------
    def _import(self):  # late import
        try:
            import akshare as ak  # type: ignore
        except Exception as e:  # noqa: BLE001
            raise DataProviderError(f"AkShare import failed: {e}") from e
        return ak

    # ---- Symbol helpers -----------------------------------------------------
    @staticmethod
    def _to_em_symbol(symbol: str) -> str:
        s = symbol.strip().lower()
        if "." in s:
            return s.split(".", 1)[0]
        for p in ("sh", "sz", "bj"):
            if s.startswith(p):
                return s[len(p):]
        return s

    @staticmethod
    def _to_prefixed_symbol(symbol: str) -> str:
        s = symbol.strip()
        if s.lower().startswith(("sh", "sz", "bj")):
            return s.lower()
        if "." in s:
            core, suf = s.split(".", 1)
            suf = suf.lower()
            if suf == "sh":
                return f"sh{core}"
            if suf == "sz":
                return f"sz{core}"
            if suf == "bj":
                return f"bj{core}"
            return f"sz{core}"
        if s.startswith("6"):
            return f"sh{s}"
        if s[:1] in {"0", "2", "3"} or s.startswith("399"):
            return f"sz{s}"
        if s[:1] in {"4", "8", "9"}:
            return f"bj{s}"
        return f"sz{s}"

    # ---- Route to source helper --------------------------------------------
    def _src_for_route(self, route: str) -> str:
        r = (route or "").strip().lower()
        if r == "sina":
            return self.SRC_SINA
        if r == "em":
            return self.SRC_EM
        return f"akshare:{r}"

    # ---- Spot snapshot with priority routing --------------------------------
    def get_spot_snapshot(self):  # noqa: ANN001
        ak = self._import()
        cfg = load_config()
        routes: List[str] = list(getattr(cfg, "ak_spot_priority", ["sina", "em"]))
        t0 = time.time()
        attempts: List[Dict[str, Any]] = []
        try:
            print(f"[快照] 路由优先级={','.join(routes)} 超时={self.timeout_sec}s", flush=True)
        except Exception:
            pass

        # Memory TTL cache (<=30s)
        try:
            if self._snapshot_cache_df is not None and self._snapshot_cache_ts is not None:
                age = time.time() - float(self._snapshot_cache_ts)
                if age <= 30:
                    attempts.append({"source": self.SRC_CACHE, "ok": True, "rows": int(len(self._snapshot_cache_df))})
                    meta = {
                        "source": self.SRC_CACHE,
                        "cache": "memory",
                        "fallback": False,
                        "stale": False,
                        "missing": False,
                        "elapsed_sec": 0.0,
                        "skipped_routes": [],
                        "attempts": attempts,
                    }
                    if self._snapshot_cache_source:
                        meta["cache_of"] = self._snapshot_cache_source
                    self._last_snapshot_meta = meta
                    try:
                        print(f"[快照] 命中内存缓存 rows={int(len(self._snapshot_cache_df))} age={age:.1f}s", flush=True)
                    except Exception:
                        pass
                    return self._snapshot_cache_df
        except Exception:
            pass

        last_err: Optional[Exception] = None
        for route in routes:
            try:
                try:
                    print(f"[快照] 尝试 route={route}", flush=True)
                except Exception:
                    pass
                if route == "sina":
                    df = ak.stock_zh_a_spot()
                    if df is None or len(df) == 0:
                        raise DataProviderError("AkShare Sina snapshot empty")
                    src = self._src_for_route("sina")
                    attempts.append({"source": src, "ok": True, "rows": int(len(df))})
                    self._last_snapshot_meta = {
                        "source": src,
                        "fallback": False,
                        "stale": False,
                        "missing": False,
                        "elapsed_sec": round(time.time() - t0, 2),
                        "skipped_routes": [],
                        "attempts": attempts,
                    }
                    try:
                        print(f"[快照] 命中 route=sina rows={int(len(df))} elapsed={round(time.time()-t0,2)}s", flush=True)
                    except Exception:
                        pass
                    self._update_snapshot_cache(df)
                    return df
                if route == "em":
                    df = self._call_with_retry(lambda: self._with_requests_timeout(lambda: ak.stock_zh_a_spot_em()), retries=1)
                    if df is None or len(df) == 0:
                        raise DataProviderError("AkShare EM snapshot empty")
                    src = self._src_for_route("em")
                    attempts.append({"source": src, "ok": True, "rows": int(len(df))})
                    self._last_snapshot_meta = {
                        "source": src,
                        "fallback": False,
                        "stale": False,
                        "missing": False,
                        "elapsed_sec": round(time.time() - t0, 2),
                        "skipped_routes": [],
                        "attempts": attempts,
                    }
                    try:
                        print(f"[快照] 命中 route=em rows={int(len(df))} elapsed={round(time.time()-t0,2)}s", flush=True)
                    except Exception:
                        pass
                    self._update_snapshot_cache(df)
                    return df
            except Exception as e:  # noqa: BLE001
                last_err = e
                attempts.append({"source": self._src_for_route(route), "ok": False, "err": f"{type(e).__name__}: {e}"})
                try:
                    print(f"[快照] 失败 route={route} err={type(e).__name__}: {e}", flush=True)
                except Exception:
                    pass
                continue

        # No live route works
        self._last_snapshot_meta = {
            "source": None,
            "fallback": False,
            "stale": False,
            "missing": True,
            "elapsed_sec": round(time.time() - t0, 2),
            "skipped_routes": [],
            "attempts": attempts,
            "error": (f"{type(last_err).__name__}: {last_err}" if last_err else None),
        }
        try:
            print(f"[快照] 全部路由失败 error={type(last_err).__name__ if last_err else 'None'}; attempts={len(attempts)}", flush=True)
        except Exception:
            pass
        raise DataProviderError(f"AkShare snapshot failed: {type(last_err).__name__}: {last_err}")

    def last_snapshot_meta(self) -> Dict[str, Any]:
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
            "attempts": [],
        }
        base.update(self._last_snapshot_meta or {})
        # strip accidental whitespace in source
        if isinstance(base.get("source"), str):
            base["source"] = base["source"].strip()
        if base.get("attempts") is None:
            base["attempts"] = []
        if base.get("skipped_routes") is None:
            base["skipped_routes"] = []
        return base

    def spot_snapshot(self):  # noqa: ANN001
        df = self.get_spot_snapshot()
        return df, self.last_snapshot_meta()

    # ---- Daily bars with multi-route fallback ------------------------------
    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:  # noqa: D401
        ak = self._import()
        cfg = load_config()
        routes: List[str] = list(getattr(cfg, "ak_daily_priority", ["tx", "sina", "em"]))
        s_ymd = start.replace("-", "") if start else None
        e_ymd = end.replace("-", "") if end else None

        def _standardize(df: pd.DataFrame) -> pd.DataFrame:
            rename_map = {
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交量(股)": "volume",
                "成交额": "amount",
                "vol": "volume",
                "成交额(元)": "amount",
            }
            src = df.copy()
            for k, v in rename_map.items():
                if k in src.columns and v not in src.columns:
                    src[v] = src[k]
            # tx 场景：成交量(手) -> volume(股)
            try:
                if "volume" not in src.columns and "成交量(手)" in src.columns:
                    vv = pd.to_numeric(src["成交量(手)"], errors="coerce")
                    src["volume"] = vv * 100.0
            except Exception:
                pass
            required = ["date", "open", "high", "low", "close"]
            missing = [c for c in required if c not in src.columns]
            if missing:
                raise DataProviderError(f"missing columns: {missing}", symbol=symbol)
            # date & numerics
            try:
                src["date"] = pd.to_datetime(src["date"])  # type: ignore[assignment]
            except Exception:
                src["date"] = pd.to_datetime(src["date"].astype(str), errors="coerce")
            for c in [col for col in ["open", "high", "low", "close", "volume", "amount"] if col in src.columns]:
                src[c] = pd.to_numeric(src[c], errors="coerce")
            src = src.sort_values("date").reset_index(drop=True)
            if s_ymd or e_ymd:
                dts = src["date"]
                if s_ymd:
                    src = src[dts >= pd.to_datetime(s_ymd)].copy()
                if e_ymd:
                    src = src[dts <= pd.to_datetime(e_ymd)].copy()
            return src

        strict = bool(getattr(cfg, "strict_real_data", True))
        try:
            print(f"[日线] 开始 symbol={symbol} routes={','.join(routes)} window=[{s_ymd or '19000101'},{e_ymd or '20500101'}] strict={strict}", flush=True)
        except Exception:
            pass
        attempts: List[Dict[str, Any]] = []
        for route in routes:
            try:
                if route == "tx":
                    try:
                        print(f"[日线] 尝试 route=tx symbol={symbol}", flush=True)
                    except Exception:
                        pass
                    sym = self._to_prefixed_symbol(symbol)
                    df = ak.stock_zh_a_hist_tx(symbol=sym, start_date=s_ymd or "19000101", end_date=e_ymd or "20500101", adjust="")
                    if df is None or len(df) == 0:
                        raise RuntimeError("tx empty")
                    df = _standardize(df)
                    # STRICT_REAL_DATA=1 不允许估算 amount
                    if strict and ("amount" not in df.columns or df["amount"].isna().all()):
                        raise RuntimeError("tx missing amount under strict mode")
                    if not strict and ("amount" not in df.columns or df["amount"].isna().all()):
                        df["amount"] = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df.get("volume", 0), errors="coerce")
                    # volume 可能缺失（tx 返回仅含 amount），严格模式下直接回退；非严格可由 amount/close 近似
                    if "volume" not in df.columns or df["volume"].isna().all():
                        if strict:
                            raise RuntimeError("tx missing volume under strict mode")
                        try:
                            v = pd.to_numeric(df.get("amount", 0), errors="coerce") / pd.to_numeric(df.get("close", 0), errors="coerce")
                            df["volume"] = v.fillna(0.0)
                        except Exception as _:
                            df["volume"] = 0.0
                    self._last_daily_source = "akshare:tx"
                    attempts.append({"route": "tx", "ok": True, "rows": int(len(df))})
                    self._last_daily_attempts = attempts
                    try:
                        print(f"[日线] 命中 route=tx symbol={symbol} rows={len(df)}", flush=True)
                    except Exception:
                        pass
                    return df[["date", "open", "high", "low", "close", "volume", "amount"]]
                if route == "sina":
                    try:
                        print(f"[日线] 尝试 route=sina symbol={symbol}", flush=True)
                    except Exception:
                        pass
                    sym = self._to_prefixed_symbol(symbol)
                    df = ak.stock_zh_a_daily(symbol=sym, start_date=s_ymd or "19000101", end_date=e_ymd or "21000101", adjust="")
                    if df is None or len(df) == 0:
                        raise RuntimeError("sina empty")
                    df = _standardize(df)
                    if strict and ("amount" not in df.columns or df["amount"].isna().all()):
                        raise RuntimeError("sina missing amount under strict mode")
                    if not strict and ("amount" not in df.columns or df["amount"].isna().all()):
                        df["amount"] = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df.get("volume", 0), errors="coerce")
                    self._last_daily_source = "akshare:sina"
                    attempts.append({"route": "sina", "ok": True, "rows": int(len(df))})
                    self._last_daily_attempts = attempts
                    try:
                        print(f"[日线] 命中 route=sina symbol={symbol} rows={len(df)}", flush=True)
                    except Exception:
                        pass
                    return df[["date", "open", "high", "low", "close", "volume", "amount"]]
                if route == "em":
                    try:
                        print(f"[日线] 尝试 route=em symbol={symbol}", flush=True)
                    except Exception:
                        pass
                    sym = self._to_em_symbol(symbol)
                    df = ak.stock_zh_a_hist(symbol=sym, start_date=s_ymd, end_date=e_ymd, period="daily", adjust="")
                    if df is None or len(df) == 0:
                        raise RuntimeError("em empty")
                    df = _standardize(df)
                    if strict and ("amount" not in df.columns or df["amount"].isna().all()):
                        raise RuntimeError("em missing amount under strict mode")
                    if not strict and ("amount" not in df.columns or df["amount"].isna().all()):
                        df["amount"] = pd.to_numeric(df["close"], errors="coerce") * pd.to_numeric(df.get("volume", 0), errors="coerce")
                    self._last_daily_source = "akshare:em"
                    attempts.append({"route": "em", "ok": True, "rows": int(len(df))})
                    self._last_daily_attempts = attempts
                    try:
                        print(f"[日线] 命中 route=em symbol={symbol} rows={len(df)}", flush=True)
                    except Exception:
                        pass
                    return df[["date", "open", "high", "low", "close", "volume", "amount"]]
            except Exception as ex:  # noqa: BLE001
                attempts.append({"route": route, "ok": False, "err": f"{type(ex).__name__}: {ex}"})
                try:
                    print(f"[日线] 失败 route={route} symbol={symbol} err={type(ex).__name__}: {ex}", flush=True)
                except Exception:
                    pass
                continue
        self._last_daily_attempts = attempts
        msg = ", ".join([f"{a.get('route')}:" + ("ok" if a.get('ok') else str(a.get('err'))) for a in attempts]) or "no routes attempted"
        try:
            print(f"[日线] 全部路由失败 symbol={symbol} msg={msg}", flush=True)
        except Exception:
            pass
        raise DataProviderError(f"AkShare get_daily failed: {msg}", symbol=symbol)

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

    # ---- Cache helper -------------------------------------------------------
    def _update_snapshot_cache(self, df) -> None:  # noqa: ANN001
        try:
            self._snapshot_cache_df = df
            self._snapshot_cache_ts = time.time()
            src = (self._last_snapshot_meta or {}).get("source")
            # Only record real sources (sina/em), never cache
            self._snapshot_cache_source = src if src in (self.SRC_SINA, self.SRC_EM) else None
        except Exception:
            self._snapshot_cache_source = None

    # ---- Healthcheck -------------------------------------------------------
    def healthcheck(self) -> Dict[str, Any]:
        try:
            ak = self._import()
            ver = getattr(ak, "__version__", None)
            return {"name": self.name, "ok": True, "reason": None, "akshare_version": ver}
        except Exception as e:  # noqa: BLE001
            return {"name": self.name, "ok": False, "reason": str(e), "akshare_version": None}
