# 简介：行情数据枢纽（严格模式）。仅返回真实数据（或本地 fixtures），不做合成降级。
from __future__ import annotations

import json
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta, time as _time

import pandas as pd

from ..core.paths import store_dir
# unified calendar/clock provided via runtime.market_clock
from ..core.config import load_config
try:
    # Optional calendar loader (uses data/raw/trade_calendar.parquet if available)
    from ..selection_engine.modes.service import _load_trade_calendar  # type: ignore
except Exception:  # pragma: no cover
    _load_trade_calendar = None  # type: ignore
from ..core.config import load_config
from ..providers.factory import get_provider
from ..tools.market_data import normalize_daily_ohlcv
from ..search.history_store import (
    canonical_query_id,
    ensure_query,
    compute_next_range,
    upsert_items,
    list_items as _list_items,
    query_meta as _query_meta,
    count_items as _count_items,
)


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

    def _normalize_as_of(self, as_of: Optional[str]) -> Optional[pd.Timestamp]:
        if as_of is None:
            return None
        try:
            return pd.to_datetime(as_of).normalize()
        except Exception:
            try:
                return pd.to_datetime(str(as_of).split("T", 1)[0]).normalize()
            except Exception:
                return None

    def _apply_as_of(self, df: Optional[pd.DataFrame], as_of: Optional[str]) -> Optional[pd.DataFrame]:
        if df is None:
            return None
        if as_of is None or len(df) == 0:
            return df
        cutoff = self._normalize_as_of(as_of)
        if cutoff is None:
            return df
        out = df.copy()
        if "date" in out.columns:
            try:
                out["date"] = pd.to_datetime(out["date"], errors="coerce")
                out = out[out["date"].notna() & (out["date"] <= cutoff)]
                if len(out) == 0:
                    return out.reset_index(drop=True)
                return out.sort_values("date").reset_index(drop=True)
            except Exception:
                return df
        try:
            idx = out.index
            if hasattr(idx, "dtype") and str(getattr(idx, "dtype", "")).startswith("datetime64"):
                out = out[idx <= cutoff]
                return out.reset_index(drop=False) if len(out) == 0 else out
        except Exception:
            pass
        return df

    def daily_ohlcv(self, symbol: str, as_of: Optional[str] = None, min_len: int = 250, *, prefer_cache_only: bool = False, force_network: bool = False) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        cfg = load_config()
        df: Optional[pd.DataFrame] = None if cfg.strict_real_data else self._from_fixtures(symbol)
        meta: Dict[str, Any] = {"source": None}

        # Cache-first via history_store
        provider = get_provider()
        qparams = {"kind": "daily", "symbol": str(symbol), "provider": provider.name}
        qid = canonical_query_id(qparams)
        ensure_query(qid, qparams)

        # Network decision; force_network overrides TTL and other gates
        # In addition, allow a process-level override for short backfill during a forced refresh run.
        force_ctx = (os.getenv("GP_FORCE_DATA_REFRESH", "").strip().lower() in {"1", "true", "yes"})
        do_network = True if (force_network or force_ctx) else (not prefer_cache_only)
        # track provenance/merge stats
        # 使用 COUNT(*) 避免 JSON 解码全量行带来的额外 CPU/IO
        rows_before = _count_items(qid)
        network_attempted = False
        network_error: Optional[str] = None
        rows_new_from_network = 0
        # TTL gating: if last_fetch_at within TTL, skip network
        try:
            ttl = int(getattr(cfg, "cache_refresh_ttl_sec", 300))
            if ttl > 0 and not force_network:
                meta_q = _query_meta(qid)
                lfa = meta_q.get("last_fetch_at")
                if isinstance(lfa, str) and lfa.strip():
                    try:
                        last = datetime.fromisoformat(lfa)
                    except Exception:
                        last = None
                    if last is not None:
                        now = datetime.now(tz=timezone.utc)
                        age = (now - (last if last.tzinfo else last.replace(tzinfo=timezone.utc))).total_seconds()
                        if age <= ttl:
                            do_network = False
        except Exception:
            pass

        # Day-rollover/trading-day guard: if cached last_item_time < target trading day, force a network attempt
        try:
            if not prefer_cache_only and not force_network:
                meta_q = _query_meta(qid)
                last_item_time = meta_q.get("last_item_time")
                # Resolve target trading day (on/before as_of; else today in configured TZ)
                def _resolve_target(as_of_str: Optional[str]) -> pd.Timestamp:
                    """Resolve the effective target trading day using unified market clock.

                    - If as_of provided: snap to last open day on/before as_of.
                    - If as_of None: use compute_market_state().target_daybook_effective_day.
                    """
                    try:
                        if as_of_str is not None:
                            base = pd.to_datetime(as_of_str).normalize()
                            cal = _load_trade_calendar() if _load_trade_calendar else None
                            if isinstance(cal, pd.DataFrame) and not cal.empty and {"cal_date", "is_open"} <= set(cal.columns):
                                ymd = base.strftime("%Y%m%d")
                                sub = cal[(cal["cal_date"] <= ymd) & (cal["is_open"] == 1)]
                                if not sub.empty:
                                    return pd.to_datetime(str(sub.iloc[-1]["cal_date"]).strip()).normalize()
                            # Fallback weekday-only
                            d = base
                            while d.weekday() >= 5:
                                d = d - pd.Timedelta(days=1)
                            return d.normalize()
                        else:
                            from ..runtime.market_clock import compute_market_state  # lazy import to avoid cycles
                            ms = compute_market_state()
                            return pd.to_datetime(ms.target_daybook_effective_day).normalize()
                    except Exception:
                        return (pd.to_datetime(as_of_str).normalize() if as_of_str is not None else pd.Timestamp.now().normalize())

                target = _resolve_target(as_of)
                if last_item_time is None:
                    do_network = True
                    meta["rollover_forced"] = True
                    meta["target_trading_day"] = target.date().isoformat()
                else:
                    try:
                        last_d = pd.to_datetime(last_item_time).normalize()
                        if last_d < target:
                            do_network = True
                            meta["rollover_forced"] = True
                            meta["target_trading_day"] = target.date().isoformat()
                    except Exception:
                        do_network = True
                        meta["rollover_forced"] = True
                        meta["target_trading_day"] = target.date().isoformat()
        except Exception:
            # Non-fatal; keep previous decision
            pass
        if do_network:
            # Short backfill window: default 2 days; allow override under forced refresh context
            try:
                backfill_days = int(os.getenv("GP_FORCE_REFRESH_LOOKBACK_DAYS", "3")) if force_ctx else 2
            except Exception:
                backfill_days = 3 if force_ctx else 2
            start, end = compute_next_range(qid, user_start=None, user_end=as_of, safety_lookback_days=backfill_days)
            def _date_only(s: Optional[str]) -> Optional[str]:
                if s is None:
                    return None
                try:
                    return pd.to_datetime(s).date().isoformat()
                except Exception:
                    return s.split("T", 1)[0]
            try:
                raw = provider.get_daily(symbol, start=_date_only(start), end=_date_only(end))
                df_norm_tmp, _ = normalize_daily_ohlcv(raw)
                items = []
                for _, r in df_norm_tmp.iterrows():
                    d = pd.to_datetime(r["date"]).date().isoformat()
                    items.append({
                        "id": d,
                        "date": d,
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                        "volume": float(r["volume"]),
                        "amount": float(r.get("amount", 0.0) or 0.0),
                    })
                stat = upsert_items(qid, items, id_key="id", time_key="date", etag_key=None)
                network_attempted = True
                try:
                    rows_new_from_network = int((stat or {}).get("inserted", 0)) + int((stat or {}).get("updated", 0))
                except Exception:
                    rows_new_from_network = 0
            except Exception as e:  # noqa: BLE001
                network_attempted = True
                network_error = f"{type(e).__name__}: {e}"

        rows = _list_items(qid)
        if rows:
            df = pd.DataFrame([r["payload"] for r in rows])
            df["date"] = pd.to_datetime(df["date"])  # type: ignore[assignment]
            for c in ["open", "high", "low", "close", "volume", "amount"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.sort_values("date").reset_index(drop=True)
            df = self._apply_as_of(df, as_of)
            meta["source"] = ("store+network_merge" if network_attempted and rows_new_from_network > 0 else (meta.get("source") or f"store:daily:{provider.name}"))
            meta["rows_total"] = len(df)
            try:
                meta["rows_new"] = max(0, len(rows) - rows_before)
            except Exception:
                meta["rows_new"] = None
            meta["attempted"] = network_attempted
            if network_error:
                meta["error"] = network_error
        else:
            if df is None and not prefer_cache_only:
                raw = provider.get_daily(symbol, start=None, end=as_of)
                df = self._apply_as_of(raw, as_of)
                src = getattr(provider, "_last_daily_source", None)
                meta["source"] = src or f"provider:{provider.name}"
                try:
                    atts = getattr(provider, "_last_daily_attempts", None)
                    if atts is not None:
                        meta["attempts"] = atts
                except Exception:
                    pass
        if df is None:
            raise ValueError(f"daily_ohlcv: 无法获取真实数据 symbol={symbol}")
        # Optional full backfill when history too short and network allowed
        if not prefer_cache_only:
            try:
                if df is not None and len(df) < max(1, int(min_len)):
                    raw_full = provider.get_daily(symbol, start=None, end=as_of)
                    df_full, _ = normalize_daily_ohlcv(raw_full)
                    df_full = self._apply_as_of(df_full, as_of)
                    items_full = []
                    for _, r in df_full.iterrows():
                        d = pd.to_datetime(r["date"]).date().isoformat()
                        items_full.append({
                            "id": d,
                            "date": d,
                            "open": float(r["open"]),
                            "high": float(r["high"]),
                            "low": float(r["low"]),
                            "close": float(r["close"]),
                            "volume": float(r["volume"]),
                            "amount": float(r.get("amount", 0.0) or 0.0),
                        })
                    upsert_items(qid, items_full, id_key="id", time_key="date", etag_key=None)
                    rows2 = _list_items(qid)
                    if rows2:
                        df2 = pd.DataFrame([r["payload"] for r in rows2])
                        df2["date"] = pd.to_datetime(df2["date"])  # type: ignore[assignment]
                        for c in ["open", "high", "low", "close", "volume", "amount"]:
                            if c in df2.columns:
                                df2[c] = pd.to_numeric(df2[c], errors="coerce")
                        df2 = df2.sort_values("date").reset_index(drop=True)
                        df2 = self._apply_as_of(df2, as_of)
                        df = df2
                        meta["source"] = "store+network_merge"
                        meta["rows_total"] = len(df)
                        try:
                            meta["rows_new"] = max(0, len(rows2) - rows_before)
                        except Exception:
                            pass
                        meta["backfill"] = True
                        meta["backfill_reason"] = "cache_too_short"
            except Exception as e:  # noqa: BLE001
                meta.setdefault("errors", []).append({"stage": "backfill", "error": f"{type(e).__name__}: {e}"})

        df = self._apply_as_of(df, as_of)
        df_norm, m = normalize_daily_ohlcv(df)
        meta.update(m)
        meta["requested_as_of"] = as_of
        meta["len"] = len(df_norm)
        meta["insufficient_history"] = len(df_norm) < min_len
        df_norm.attrs.update(meta)
        return df_norm, meta

    def daily_ohlcv_batch(self, symbols: list[str], as_of: Optional[str] = None, *, safety_lookback_days: int = 2) -> Dict[str, Tuple[pd.DataFrame, Dict[str, Any]]]:
        if not symbols:
            return {}
        provider = get_provider()
        cfg = load_config()
        # Resolve target trading day using unified market clock
        def _resolve_target(as_of_str: Optional[str]) -> pd.Timestamp:
            try:
                if as_of_str is not None:
                    base = pd.to_datetime(as_of_str).normalize()
                    cal = _load_trade_calendar() if _load_trade_calendar else None
                    if isinstance(cal, pd.DataFrame) and not cal.empty and {"cal_date", "is_open"} <= set(cal.columns):
                        ymd = base.strftime("%Y%m%d")
                        sub = cal[(cal["cal_date"] <= ymd) & (cal["is_open"] == 1)]
                        if not sub.empty:
                            return pd.to_datetime(str(sub.iloc[-1]["cal_date"]))
                    # fallback weekend-step back
                    d = base
                    while d.weekday() >= 5:
                        d = d - pd.Timedelta(days=1)
                    return d
                else:
                    from ..runtime.market_clock import compute_market_state  # lazy import
                    ms = compute_market_state()
                    return pd.to_datetime(ms.target_daybook_effective_day)
            except Exception:
                return (pd.to_datetime(as_of_str).normalize() if as_of_str is not None else pd.Timestamp.now().normalize())

        target = _resolve_target(as_of).normalize()
        # compute minimal start across symbols
        starts = []
        qids: Dict[str, str] = {}
        skip_symbols: set[str] = set()
        behind_symbols: set[str] = set()
        for s in symbols:
            qparams = {"kind": "daily", "symbol": str(s), "provider": provider.name}
            qid = canonical_query_id(qparams)
            qids[s] = qid
            ensure_query(qid, qparams)
            # per-symbol TTL gating
            try:
                ttl = int(getattr(load_config(), "cache_refresh_ttl_sec", 300))
                if ttl > 0:
                    meta_q = _query_meta(qid)
                    lfa = meta_q.get("last_fetch_at")
                    lit = meta_q.get("last_item_time")
                    is_behind = False
                    try:
                        if isinstance(lit, str) and lit.strip():
                            ld = pd.to_datetime(lit).normalize()
                            is_behind = (ld < target)
                    except Exception:
                        is_behind = True  # if unparsable, err on refresh
                    if isinstance(lfa, str) and lfa.strip():
                        last = None
                        try:
                            last = datetime.fromisoformat(lfa)
                        except Exception:
                            pass
                        if last is not None:
                            now = datetime.now(tz=timezone.utc)
                            age = (now - (last if last.tzinfo else last.replace(tzinfo=timezone.utc))).total_seconds()
                            if age <= ttl and not is_behind:
                                skip_symbols.add(s)
                                continue
                    if is_behind:
                        behind_symbols.add(s)
            except Exception:
                pass
            st, _ = compute_next_range(qid, user_start=None, user_end=as_of, safety_lookback_days=safety_lookback_days)
            if st:
                starts.append(st)
        def _date_only(s: Optional[str]) -> Optional[str]:
            if s is None:
                return None
            try:
                return pd.to_datetime(s).date().isoformat()
            except Exception:
                return s.split("T", 1)[0]
        start = _date_only(min(starts) if starts else None)
        end = _date_only(as_of)

        # Fetch batch and upsert
        # Always fetch symbols that are behind target trading day regardless of TTL
        fetch_list = [s for s in symbols if (s not in skip_symbols) or (s in behind_symbols)]
        raw_map = provider.get_daily_batch(fetch_list, start=start, end=end) if fetch_list else {}
        for s, raw in raw_map.items():
            try:
                df_norm, _ = normalize_daily_ohlcv(raw)
            except Exception:
                continue
            items = []
            for _, r in df_norm.iterrows():
                d = pd.to_datetime(r["date"]).date().isoformat()
                items.append({
                    "id": d,
                    "date": d,
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                    "amount": float(r.get("amount", 0.0) or 0.0),
                })
            upsert_items(qids[s], items, id_key="id", time_key="date", etag_key=None)

        # Return mapping from cache
        out: Dict[str, Tuple[pd.DataFrame, Dict[str, Any]]] = {}
        for s in symbols:
            rows = _list_items(qids[s])
            if not rows:
                continue
            df = pd.DataFrame([r["payload"] for r in rows])
            df["date"] = pd.to_datetime(df["date"])  # type: ignore[assignment]
            for c in ["open", "high", "low", "close", "volume", "amount"]:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.sort_values("date").reset_index(drop=True)
            df = self._apply_as_of(df, as_of)
            df_norm, m = normalize_daily_ohlcv(df)
            meta = {"source": f"store:daily:{provider.name}", **m, "requested_as_of": as_of, "len": len(df_norm), "insufficient_history": False}
            df_norm.attrs.update(meta)
            out[s] = (df_norm, meta)
        return out

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
            import unicodedata, re
            x = unicodedata.normalize("NFKC", (s or "")).strip().lower()
            x = x.replace("(", "").replace(")", "").replace("%", "")
            x = re.sub(r"\\s+", "", x)
            return x
        def _pick(df, cands):
            cmap = { _norm(c): c for c in df.columns }
            for k in cands:
                nk = _norm(k)
                if nk in cmap:
                    return cmap[nk]
        amt_src = _pick(snap, ["amount", "turnover"])
        if amt_src and "amount" not in snap.columns:
            snap = snap.copy(); snap["amount"] = snap[amt_src]
        chg_src = _pick(snap, ["pct_chg", "changepct", "change_pct", "pct_change"])
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
