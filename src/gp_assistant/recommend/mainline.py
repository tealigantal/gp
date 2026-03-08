from __future__ import annotations

from typing import Any, Dict, List, Optional

import time
import os
import json
from datetime import datetime, timezone

import pandas as pd
from ..core.config import load_config
from ..core.paths import cache_dir


def _with_requests_timeout(fn):  # noqa: ANN001
    try:
        cfg = load_config()
        timeout_sec = int(getattr(cfg, "request_timeout_sec", 20))
    except Exception:
        timeout_sec = 20
    import requests  # type: ignore
    original = requests.sessions.Session.request

    def wrapped(session, method, url, **kwargs):  # noqa: ANN001
        to = kwargs.get("timeout", None)
        if to is None or (isinstance(to, (int, float)) and to < timeout_sec):
            kwargs["timeout"] = timeout_sec
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


def _call_with_retry(fn, retries: int = 3):  # noqa: ANN001
    import time as _t
    import random as _r
    for i in range(retries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            if i == retries - 1:
                raise e
            _t.sleep((2 ** i) + _r.random() * 0.5)


def _iso_now() -> str:
    try:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    except Exception:
        return str(datetime.now())


def _detect_col(cols: List[str], keywords: List[str]) -> Optional[str]:
    s = [str(c) for c in cols]
    for kw in keywords:
        for c in s:
            if kw in str(c):
                return c
    return None


def _cache_path(indicator: str):
    try:
        from ..core.paths import store_dir
        safe = "".join([ch if ch.isalnum() else "_" for ch in str(indicator)]) or "today"
        p = store_dir() / "cache" / f"mainline_fundflow_{safe}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        return None


def _read_cache(indicator: str) -> Optional[Dict[str, Any]]:
    p = _cache_path(indicator)
    if p is None or not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_cache(indicator: str, obj: Dict[str, Any]) -> None:
    p = _cache_path(indicator)
    if p is None:
        return
    try:
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def build_mainline(indicator: str = "今日", topn: int = 3, snapshot: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """Build mainline/主线 via AkShare sector fund flow rank.

    Tries both 行业资金流 and 概念资金流, selects topn by 主力净流入-净额.
    """
    try:
        import akshare as ak  # type: ignore
    except Exception as e:  # noqa: BLE001
        # try cache fallback
        cache = _read_cache(indicator)
        if cache:
            cache.setdefault("source", "cache:disk")
            cache.setdefault("as_of_ts", _iso_now())
            cache.setdefault("errors", [f"stale_cache_used;akshare_import_failed:{e}"])
            return cache
        return {"indicator": indicator, "sectors": [], "as_of_ts": _iso_now(), "errors": [f"akshare_import_failed:{e}"]}

    out_sectors: List[Dict[str, Any]] = []
    errors: List[str] = []

    # Snapshot industry aggregation priority when available
    try:
        if snapshot is not None and isinstance(snapshot, pd.DataFrame) and (not snapshot.empty) and ("行业" in [str(c) for c in snapshot.columns]):
            df = snapshot.copy()
            # Strict mainboard-only universe for mainline aggregation
            try:
                from providers.boards import is_mainboard  # lazy import to avoid cycles
                code_col = "代码" if "代码" in df.columns else ("code" if "code" in df.columns else None)
                if code_col:
                    df = df[df[code_col].astype(str).map(is_mainboard)]
            except Exception:
                pass
            # choose metric: sum of 成交额 if present, otherwise mean of chg/pct_chg
            cols = set(map(str, df.columns))
            use_amt = "成交额" in cols
            if use_amt:
                g = df.groupby("行业")["成交额"].sum().sort_values(ascending=False).head(max(0, int(topn)))
                for name, amt in g.items():
                    out_sectors.append({"sector_type": "snapshot", "name": str(name), "pct_chg": None, "main_inflow": str(amt), "main_inflow_pct": None, "leader_stock": None, "source": "snapshot:industry_agg", "indicator": indicator})
                return {"indicator": indicator, "sectors": out_sectors, "as_of_ts": _iso_now(), "errors": [], "source": "snapshot:industry_agg"}
    except Exception as _e:
        pass

    # TTL gating for cache
    try:
        ttl = int(os.getenv("GP_MAINLINE_TTL_SEC", "300"))
    except Exception:
        ttl = 300
    cache = _read_cache(indicator)
    if cache and (time.time() - float(cache.get("ts", 0.0)) <= ttl):
        cache.setdefault("source", "cache:disk")
        cache.setdefault("as_of_ts", _iso_now())
        cache.setdefault("errors", [])
        cache.setdefault("indicator", indicator)
        return cache
    for sector_type in ["行业资金流", "概念资金流"]:
        try:
            df = _call_with_retry(lambda: _with_requests_timeout(lambda: ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type=sector_type)), retries=3)  # type: ignore[attr-defined]
            if isinstance(df, pd.DataFrame) and not df.empty:
                x = df.copy()
                cols = [str(c) for c in x.columns]
                chg_col = None
                for cand in ["涨跌幅", "涨跌幅(%)", "涨跌"]:
                    if cand in cols:
                        chg_col = cand
                        break
                inflow_col = None
                for cand in ["主力净流入-净额", "主力净流入净额", "主力净流入净额(亿)"]:
                    if cand in cols or any(cand in c for c in cols):
                        inflow_col = _detect_col(cols, [cand])
                        break
                inflow_pct_col = _detect_col(cols, ["主力净流入-净占比", "主力净流入净占比"])
                name_col = "名称" if "名称" in cols else ("板块名称" if "板块名称" in cols else str(cols[0]))
                if inflow_col is None:
                    inflow_col = name_col  # fallback to avoid crash; sorted won't work
                try:
                    x["_inflow"] = pd.to_numeric(x[inflow_col].astype(str).str.replace(",", ""), errors="coerce")
                except Exception:
                    x["_inflow"] = pd.to_numeric(x.get(inflow_col), errors="coerce")
                x = x.sort_values("_inflow", ascending=False)
                for _, r in x.head(max(0, int(topn))).iterrows():
                    item = {
                        "sector_type": sector_type,
                        "name": str(r.get(name_col)),
                        "pct_chg": None if chg_col is None else str(r.get(chg_col)),
                        "main_inflow": None if inflow_col is None else str(r.get(inflow_col)),
                        "main_inflow_pct": None if inflow_pct_col is None else str(r.get(inflow_pct_col)),
                        "leader_stock": r.get("领涨股") if "领涨股" in cols else None,
                        "source": "akshare:stock_sector_fund_flow_rank",
                        "indicator": indicator,
                    }
                    out_sectors.append(item)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{sector_type}:{e}")
            continue
    result = {"indicator": indicator, "sectors": out_sectors, "as_of_ts": _iso_now(), "errors": errors, "source": "akshare:stock_sector_fund_flow_rank"}
    if out_sectors:
        try:
            obj = dict(result)
            obj["ts"] = time.time()
            _write_cache(indicator, obj)
        except Exception:
            pass
        # persist simplified pickle cache
        try:
            pd.to_pickle(result, cache_dir() / "mainline.pkl")
        except Exception:
            pass
        return result
    # Network failed -> stale cache fallback
    try:
        max_stale = int(os.getenv("GP_MAINLINE_MAX_STALE_SEC", "86400"))
    except Exception:
        max_stale = 86400
    cache2 = _read_cache(indicator)
    if cache2 and (time.time() - float(cache2.get("ts", 0.0)) <= max_stale):
        cache2.setdefault("source", "cache:disk")
        errs = list(errors)
        errs.append("stale_cache_used")
        cache2["errors"] = errs
        cache2.setdefault("as_of_ts", _iso_now())
        cache2.setdefault("indicator", indicator)
        return cache2
    # pickle fallback as last resort
    try:
        pkl = cache_dir() / "mainline.pkl"
        if pkl.exists():
            data = pd.read_pickle(pkl)
            if isinstance(data, dict):
                data.setdefault("indicator", indicator)
                data.setdefault("as_of_ts", _iso_now())
                data.setdefault("source", "cache:file")
                data.setdefault("errors", list(errors) + ["stale_cache_used"])  # type: ignore[arg-type]
                return data
    except Exception:
        pass
    return result
