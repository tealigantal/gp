"""Candidate generation with diagnostics and locale-safe column handling."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
import os
from concurrent.futures import ProcessPoolExecutor, as_completed


# 顶层 worker，便于多进程 pickling（Windows/Docker 下必须是模块级）
def _build_candidate_worker(entry: Dict[str, Any], env_grade_in: str) -> Dict[str, Any]:
    from .datahub import MarketDataHub as _Hub
    from ..strategy.indicators import compute_indicators as _ind
    from ..strategy.chip_model import compute_chip as _chip
    from ..risk.noise_q import grade_noise as _grade
    from ..core.config import load_config as _load_cfg
    import pandas as _pd

    _cfg = _load_cfg()
    _hub = _Hub()
    sym = entry.get("code")
    try:
        df, meta = _hub.daily_ohlcv(sym, None, min_len=250)
    except Exception as e:  # noqa: BLE001
        return {"symbol": sym, "status": "skip", "skipped_sample": True, "reason": f"fetch_fail:{e}", "src": None, "len": None, "attempts": None}
    bars_too_short = False
    try:
        if bool(meta.get("insufficient_history")):
            bars_too_short = True
    except Exception:
        pass
    indicator_first_fail = False
    try:
        feat = _ind(df)
    except Exception:
        indicator_first_fail = True
        try:
            feat = _ind(df)
        except Exception as e:  # noqa: BLE001
            return {"symbol": sym, "status": "skip", "skipped_sample": True, "indicator_error": True, "reason": f"indicator_fail:{e}", "src": meta.get("source"), "len": meta.get("len"), "attempts": meta.get("attempts")}
    last = feat.iloc[-1]
    avg5_amount = float(feat["amount_5d_avg"].iloc[-1]) if "amount_5d_avg" in feat.columns and not _pd.isna(feat["amount_5d_avg"].iloc[-1]) else 0.0
    atrp = float(last.get("atr_pct", 0.0)) if not _pd.isna(last.get("atr_pct", 0.0)) else 0.0
    gap = float(last.get("gap_pct", 0.0)) if not _pd.isna(last.get("gap_pct", 0.0)) else 0.0
    close = float(last.get("close", 0.0)) if not _pd.isna(last.get("close", 0.0)) else 0.0
    ma20 = float(last.get("ma20", 0.0)) if not _pd.isna(last.get("ma20", 0.0)) else 0.0
    pressure = {"near_ma20": bool(ma20 and abs((close - ma20) / ma20) <= 0.005)}
    chip, chip_meta = _chip(feat)
    q_grade = _grade(feat, env_grade_in)
    if avg5_amount < _cfg.min_avg_amount:
        return {
            "symbol": sym,
            "status": "veto",
            "veto": {"symbol": sym, "reason": "LOW_LIQ_HARD", "amount_5d_avg": avg5_amount},
            "bars_too_short": bars_too_short,
            "indicator_first_fail": indicator_first_fail,
            "src": meta.get("source"),
            "len": meta.get("len"),
            "avg5": avg5_amount,
            "attempts": meta.get("attempts"),
        }
    cand = {
        "symbol": sym,
        "name": entry.get("name"),
        "industry": entry.get("industry"),
        "source_reason": "动态候选",
        "liquidity": {"avg5_amount": avg5_amount, "grade": _liquidity_grade(avg5_amount)},
        "atr_pct": atrp,
        "gap_pct": gap,
        "pressure_flags": pressure,
        "q_grade": q_grade,
        "chip": chip.__dict__,
        "indicators": {
            "ma20": ma20,
            "slope20": float(feat["slope20"].iloc[-1]) if "slope20" in feat.columns else 0.0,
            "atr_pct": atrp,
            "gap_pct": gap,
        },
        "close": close,
    }
    observe_only = False
    reasons: List[str] = []
    if cand["liquidity"]["grade"] == "C":
        observe_only = True
        reasons.append("LIQ_C_OBSERVE")
    if atrp > 0.08:
        observe_only = True
        reasons.append("ATR_HIGH_OBSERVE")
    if gap > 0.02:
        observe_only = True
        reasons.append("GAP_HIGH_FORBID")
    if getattr(chip, "dist_to_90_high_pct", 1.0) <= 0.02:
        observe_only = True
        reasons.append("NEAR_CHIP90_HIGH_FORBID")
    cand["flags"] = {"must_observe_only": bool(observe_only), "reasons": reasons}
    return {
        "symbol": sym,
        "status": "cand",
        "cand": cand,
        "bars_too_short": bars_too_short,
        "indicator_first_fail": indicator_first_fail,
        "src": meta.get("source"),
        "len": meta.get("len"),
        "avg5": avg5_amount,
        "liq": cand["liquidity"]["grade"],
        "atr": atrp,
        "gap": gap,
        "obs": bool(cand["flags"]["must_observe_only"]),
        "obs_reasons": reasons,
        "attempts": meta.get("attempts"),
    }

import pandas as pd

from .datahub import MarketDataHub
from ..strategy.indicators import compute_indicators
from ..strategy.chip_model import compute_chip
from ..risk.noise_q import grade_noise
from ..core.config import load_config


def _build_dynamic_universe_symbols(snapshot: Optional[pd.DataFrame] = None) -> List[Dict[str, Any]]:
    """Build dynamic universe using spot snapshot with basic filters.

    Filters (configurable via AppConfig):
    - Exclude ST/*ST/退
    - Price in [price_min, price_max]
    - Exclude newly listed within new_stock_days (if list_date available)
    - Select top N by amount (dynamic_pool_size)
    """
    if snapshot is None:
        raise RuntimeError("_build_dynamic_universe_symbols requires snapshot")
    cfg = load_config()
    snap = snapshot

    # Robust column resolution
    def _norm(s: str) -> str:
        x = (s or "").strip().lower()
        x = x.replace("（", "(").replace("）", ")").replace("％", "%").replace("%", "")
        x = "".join(x.split())
        return x

    def _pick_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
        cmap = { _norm(c): c for c in df.columns }
        for cand in candidates:
            k = _norm(cand)
            if k in cmap:
                return cmap[k]
        return None

    # Canonical columns
    code_col = _pick_col(snap, ["代码", "股票代码", "证券代码", "code", "symbol", "ts_code"])
    name_col = _pick_col(snap, ["名称", "股票名称", "证券简称", "name"])
    close_col = _pick_col(snap, ["最新价", "现价", "close", "收盘", "收盘价", "price"])
    amount_col = _pick_col(snap, ["成交额", "成交金额", "amount", "turnover", "成交额(元)"])
    list_date_col = _pick_col(snap, ["上市时间", "上市日期", "list_date", "ipo_date"])
    industry_col = _pick_col(snap, ["行业", "所属行业", "行业板块", "industry"])
    if not code_col or not close_col or not amount_col:
        raise RuntimeError("snapshot missing required columns: code/close/amount")

    df = snap.copy()
    cols: List[str] = []
    ren: Dict[str, str] = {}
    for orig, canon in ((code_col, "code"), (name_col, "name"), (close_col, "close"), (amount_col, "amount"), (list_date_col, "list_date"), (industry_col, "industry")):
        if orig:
            cols.append(orig)
            ren[orig] = canon
    df = df[cols].rename(columns=ren)
    # 兼容旧引用：提供 price 别名（=close）
    if "close" in df.columns and "price" not in df.columns:
        df["price"] = df["close"]

    # Basic filters
    if "name" in df.columns:
        mask_ok = ~df["name"].astype(str).str.upper().str.contains("ST|\*ST|退")
        df = df[mask_ok]
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    if "price" in df.columns:
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df = df[(df["price"] >= cfg.price_min) & (df["price"] <= cfg.price_max)]
    if "list_date" in df.columns:
        try:
            d = pd.to_datetime(df["list_date"], errors="coerce")
            days = (pd.Timestamp.today().normalize() - d).dt.days
            df = df[days >= cfg.new_stock_days]
        except Exception:
            pass
    df = df.sort_values("amount", ascending=False).head(cfg.dynamic_pool_size)

    # Mainline restriction (industry preferred)
    if cfg.restrict_to_mainline and "industry" in df.columns and df["industry"].notna().any():
        tmp = df.copy()
        g = tmp.groupby("industry").agg(sum_amt=("amount", "sum"), count=("code", "count")).reset_index()
        g = g.sort_values("sum_amt", ascending=False).head(max(1, cfg.mainline_top_n))
        top_groups = set(g["industry"].astype(str).tolist())
        df = df[df["industry"].astype(str).isin(top_groups)]

    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        out.append({
            "code": str(r["code"]),
            "industry": (str(r["industry"]) if "industry" in df.columns and pd.notna(r.get("industry")) else None),
            "amount": float(r.get("amount", 0.0)),
            "name": str(r.get("name")) if "name" in df.columns else None,
        })
    return out


def _liquidity_grade(avg5_amount: float) -> str:
    if avg5_amount >= 2e9:
        return "A"
    if avg5_amount >= 1e9:
        return "B"
    return "C"


def generate_candidates(symbols: List[str] | None, env_grade: str, topk: int = 3, *, snapshot: Optional[pd.DataFrame] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    cfg = load_config()
    hub = MarketDataHub()
    pool: List[Dict[str, Any]] = []
    veto_reasons: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {
        "universe_in_count": 0,
        "universe_after_filter_count": 0,
        "bars_missing_count": 0,
        "bars_too_short_count": 0,
        "indicator_error_count": 0,
        "skipped_symbols_sample": [],
        "candidates_out_count": 0,
    }
    # Build base symbols
    if symbols:
        base_entries = ([{"code": s} for s in symbols])
    else:
        if snapshot is not None:
            base_entries = _build_dynamic_universe_symbols(snapshot)
        else:
            from ..providers.universe_provider import UniverseProvider
            uni = UniverseProvider()
            syms = uni.get_symbols()
            base_entries = ([{"code": s} for s in syms])
            # enrich stats with universe meta when available
            try:
                um = uni.last_meta()
                stats["universe_raw_count"] = int(um.get("raw_count", 0))
                stats["universe_cleaned_count"] = int(um.get("cleaned_count", len(syms)))
                stats["universe_removed_counts"] = um.get("removed_counts", {})
            except Exception:
                pass
    stats["universe_in_count"] = len(base_entries)
    stats["universe_after_filter_count"] = len(base_entries)

    # --- 并行执行符号任务（保持原逻辑，只改变执行方式） ---

    total = len(base_entries)
    workers = cfg.parallel_workers if cfg.parallel_workers and cfg.parallel_workers > 0 else max(2, min(8, (os.cpu_count() or 4) * 2))
    try:
        pri = ",".join(getattr(cfg, "ak_daily_priority", ["tx", "sina", "em"]))
        strict = bool(getattr(cfg, "strict_real_data", True))
        print(f"[数据] 阶段=日线K：每日线路由优先级={pri}，严格真实={strict}", flush=True)
        print(f"[并行] 正在搜索候选，共 {total} 个标的，并发={workers}…", flush=True)
    except Exception:
        pass

    # 统计扩展：观察与跳过计数（仅用于打印，可观测，不影响口径）
    observe_count = 0
    skip_count = 0
    attempts_sample: List[Dict[str, Any]] = []
    route_hits: Dict[str, int] = {"tx": 0, "sina": 0, "em": 0, "other": 0}

    def _acc_route(src: Optional[str]) -> None:
        try:
            s = (src or "").lower()
            if "tx" in s:
                route_hits["tx"] += 1
            elif "sina" in s:
                route_hits["sina"] += 1
            elif s.endswith(":em") or "em" in s:
                route_hits["em"] += 1
            else:
                route_hits["other"] += 1
        except Exception:
            route_hits["other"] += 1

    if total <= 4 or workers <= 1:
        for entry in base_entries:
            r = _build_candidate_worker(entry, env_grade)
            if r.get("status") == "cand":
                pool.append(r["cand"]) 
                if r.get("obs"):
                    observe_count += 1
                _acc_route(r.get("src"))
            elif r.get("status") == "veto":
                veto_reasons.append(r["veto"]) 
                _acc_route(r.get("src"))
            else:
                skip_count += 1
                _acc_route(r.get("src"))
                if r.get("reason", "").startswith("fetch_fail"):
                    stats["bars_missing_count"] += 1
                if r.get("indicator_error"):
                    stats["indicator_error_count"] += 1
                if r.get("bars_too_short"):
                    stats["bars_too_short_count"] += 1
                if r.get("skipped_sample") and len(stats["skipped_symbols_sample"]) < 10:
                    stats["skipped_symbols_sample"].append(r.get("symbol"))
            if r.get("indicator_first_fail"):
                stats["indicator_error_count"] += 1
            # 尝试样本收集（轻量，仅前 30 条）
            try:
                if len(attempts_sample) < 30 and r.get("attempts") is not None:
                    attempts_sample.append({"symbol": r.get("symbol"), "src": r.get("src"), "attempts": r.get("attempts")})
            except Exception:
                pass
            # 逐项输出：本次任务结果摘要
            try:
                sym = r.get("symbol")
                status = r.get("status")
                src = r.get("src", "-")
                blen = r.get("len", "-")
                if status == "cand":
                    obs = r.get("obs")
                    liq = r.get("liq")
                    avg5 = r.get("avg5")
                    atr = r.get("atr")
                    gap = r.get("gap")
                    print(f"[候选] {sym} src={src} bars={blen} -> cand liq={liq} avg5={avg5:.2f} atr={atr:.2%} gap={gap:.2%} obs={obs}", flush=True)
                elif status == "veto":
                    v = r.get("veto", {})
                    print(f"[候选] {sym} src={src} bars={blen} -> veto reason={v.get('reason')} avg5={v.get('amount_5d_avg')} ", flush=True)
                else:
                    print(f"[候选] {sym} src={src} bars={blen} -> skip reason={r.get('reason')} short={r.get('bars_too_short', False)} ind_err={r.get('indicator_error', False)}", flush=True)
            except Exception:
                pass
        try:
            print(
                f"[并行] 完成 {total}/{total}，候选={len(pool)}，否决={len(veto_reasons)}，观察={observe_count}，跳过={skip_count}｜路由命中 tx={route_hits['tx']} sina={route_hits['sina']} em={route_hits['em']} other={route_hits['other']}",
                flush=True,
            )
        except Exception:
            pass
    else:
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_build_candidate_worker, entry, env_grade) for entry in base_entries]
            for fut in as_completed(futs):
                r = fut.result()
                done += 1
                if r.get("status") == "cand":
                    pool.append(r["cand"]) 
                    if r.get("obs"):
                        observe_count += 1
                    _acc_route(r.get("src"))
                elif r.get("status") == "veto":
                    veto_reasons.append(r["veto"]) 
                    _acc_route(r.get("src"))
                else:
                    skip_count += 1
                    _acc_route(r.get("src"))
                    if r.get("reason", "").startswith("fetch_fail"):
                        stats["bars_missing_count"] += 1
                    if r.get("indicator_error"):
                        stats["indicator_error_count"] += 1
                    if r.get("bars_too_short"):
                        stats["bars_too_short_count"] += 1
                    if r.get("skipped_sample") and len(stats["skipped_symbols_sample"]) < 10:
                        stats["skipped_symbols_sample"].append(r.get("symbol"))
                if r.get("indicator_first_fail"):
                    stats["indicator_error_count"] += 1
                # 尝试样本收集（轻量，仅前 30 条）
                try:
                    if len(attempts_sample) < 30 and r.get("attempts") is not None:
                        attempts_sample.append({"symbol": r.get("symbol"), "src": r.get("src"), "attempts": r.get("attempts")})
                except Exception:
                    pass
                # 逐项输出：本次任务结果摘要（并行）
                try:
                    sym = r.get("symbol")
                    status = r.get("status")
                    src = r.get("src", "-")
                    blen = r.get("len", "-")
                    if status == "cand":
                        obs = r.get("obs")
                        liq = r.get("liq")
                        avg5 = r.get("avg5")
                        atr = r.get("atr")
                        gap = r.get("gap")
                        print(f"[候选] {sym} src={src} bars={blen} -> cand liq={liq} avg5={avg5:.2f} atr={atr:.2%} gap={gap:.2%} obs={obs}", flush=True)
                    elif status == "veto":
                        v = r.get("veto", {})
                        print(f"[候选] {sym} src={src} bars={blen} -> veto reason={v.get('reason')} avg5={v.get('amount_5d_avg')} ", flush=True)
                    else:
                        print(f"[候选] {sym} src={src} bars={blen} -> skip reason={r.get('reason')} short={r.get('bars_too_short', False)} ind_err={r.get('indicator_error', False)}", flush=True)
                except Exception:
                    pass
                if (done % 10 == 0) or done == total:
                    try:
                        print(
                            f"[并行] 进度 {done}/{total}，候选={len(pool)}，否决={len(veto_reasons)}，观察={observe_count}，跳过={skip_count}｜路由命中 tx={route_hits['tx']} sina={route_hits['sina']} em={route_hits['em']} other={route_hits['other']}",
                            flush=True,
                        )
                    except Exception:
                        pass

    pool.sort(key=lambda x: (-(x["indicators"].get("slope20") or 0.0), x["atr_pct"], x["liquidity"]["grade"]))
    stats["candidates_out_count"] = len(pool)
    stats["daily_attempts_sample"] = attempts_sample
    try:
        print(
            f"[汇总] 候选={len(pool)} 否决={len(veto_reasons)} 观察={observe_count} 跳过={skip_count}｜路由命中 tx={route_hits['tx']} sina={route_hits['sina']} em={route_hits['em']} other={route_hits['other']}",
            flush=True,
        )
    except Exception:
        pass
    return pool, veto_reasons, stats
