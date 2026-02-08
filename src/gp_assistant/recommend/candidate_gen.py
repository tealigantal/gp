# 简介：候选生成器。基于基础池与市场环境生成候选标的集合，
# 同时返回被否决/过滤的原因以便调试与解释。
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pandas as pd

from .datahub import MarketDataHub
from ..strategy.indicators import compute_indicators
from ..strategy.chip_model import compute_chip
from ..risk.noise_q import grade_noise
from ..core.config import load_config
from ..providers.factory import get_provider


def _build_dynamic_universe_symbols() -> List[Dict[str, Any]]:
    """Use provider spot snapshot to build a dynamic universe by liquidity and basic filters.

    Filters (configurable via AppConfig):
    - Exclude ST/*ST/退
    - Price in [price_min, price_max]
    - Exclude newly listed within new_stock_days (if上市时间 available)
    - Select top N by 成交额 (dynamic_pool_size)
    """
    cfg = load_config()
    p = get_provider()
    try:
        snap = p.get_spot_snapshot()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"获取全市场快照失败: {e}")
    # Expect columns: 代码, 名称, 最新价/现价, 成交额, 涨跌幅, 上市时间(可选)
    code_col = "代码" if "代码" in snap.columns else ("code" if "code" in snap.columns else None)
    name_col = "名称" if "名称" in snap.columns else ("name" if "name" in snap.columns else None)
    price_col = None
    for c in ("最新价", "现价", "最新", "close", "收盘"):
        if c in snap.columns:
            price_col = c
            break
    amount_col = "成交额" if "成交额" in snap.columns else ("amount" if "amount" in snap.columns else None)
    list_date_col = None
    for c in ("上市时间", "上市日期", "list_date"):
        if c in snap.columns:
            list_date_col = c
            break
    if not code_col or not price_col or not amount_col:
        raise RuntimeError("快照缺少必要列：代码/价格/成交额")

    df = snap.copy()
    # Basic clean
    keep_cols = [code_col, name_col, price_col, amount_col] + ([list_date_col] if list_date_col else [])
    # Optional columns we may leverage for mainline restriction
    if "行业" in snap.columns and "行业" not in keep_cols:
        keep_cols.append("行业")
    if "概念" in snap.columns and "概念" not in keep_cols:
        keep_cols.append("概念")
    df = df[keep_cols].rename(columns={code_col: "code", name_col or "N": "name", price_col: "price", amount_col: "amount", **({list_date_col: "list_date"} if list_date_col else {})})
    # Filters
    # Exclude ST/*ST/退
    if "name" in df.columns:
        mask_ok = ~df["name"].astype(str).str.upper().str.contains("ST|\*ST|退")
        df = df[mask_ok]
    # Price range
    df = df[(df["price"] >= cfg.price_min) & (df["price"] <= cfg.price_max)]
    # New stock exclude if list_date available
    if "list_date" in df.columns:
        import pandas as pd
        try:
            d = pd.to_datetime(df["list_date"], errors="coerce")
            days = (pd.Timestamp.today().normalize() - d).dt.days
            df = df[days >= cfg.new_stock_days]
        except Exception:
            pass
    # Liquidity by current amount, then take top N
    df = df.sort_values("amount", ascending=False).head(cfg.dynamic_pool_size)

    # Restrict to mainline groups if enabled
    if cfg.restrict_to_mainline:
        mainline_applied = False
        import pandas as pd
        # Prefer industry column from snapshot
        if "行业" in df.columns and df["行业"].notna().any():
            tmp = df.copy()
            # If change pct not present, approximate weight by amount
            # We already filtered by amount; rank groups by sum(amount)
            g = tmp.groupby("行业").agg(sum_amt=("amount", "sum"), count=("code", "count")).reset_index()
            g = g.sort_values("sum_amt", ascending=False).head(max(1, cfg.mainline_top_n))
            top_groups = set(g["行业"].astype(str).tolist())
            df = df[df["行业"].astype(str).isin(top_groups)]
            mainline_applied = True
        else:
            # Try concepts via akshare boards
            try:
                import akshare as ak  # type: ignore
                # concept names
                try:
                    cons_name = ak.stock_board_concept_name_ths()  # type: ignore[attr-defined]
                except Exception:
                    cons_name = None
                if cons_name is not None and len(cons_name) > 0:
                    # Identify top concepts by '涨跌幅' or fallback to recent '上涨家数'
                    rank_col = None
                    for c in ("涨跌幅", "涨跌幅(%)", "涨跌", "changePct"):
                        if c in cons_name.columns:
                            rank_col = c
                            break
                    if rank_col is None:
                        # fallback: use first two concepts arbitrarily but still real; avoid synthetic scoring
                        top_concepts = [str(cons_name.iloc[0, 0]), str(cons_name.iloc[1, 0])] if len(cons_name) >= 2 else []
                    else:
                        cn = cons_name.copy()
                        try:
                            cn["_r"] = pd.to_numeric(cn[rank_col].astype(str).str.rstrip("% "), errors="coerce")
                        except Exception:
                            cn["_r"] = pd.to_numeric(cn[rank_col], errors="coerce")
                        cn = cn.sort_values("_r", ascending=False).head(max(1, cfg.mainline_top_n))
                        # assume first column is name if '板块名称' not present
                        name_col = "板块名称" if "板块名称" in cn.columns else cn.columns[0]
                        top_concepts = [str(x) for x in cn[name_col].tolist()]
                    # Fetch constituents for selected concepts
                    keep_codes: set[str] = set()
                    for name in top_concepts:
                        try:
                            dfc = ak.stock_board_concept_cons_em(symbol=name)  # type: ignore[attr-defined]
                            # columns may include 代码/股票代码/code
                            code_c = None
                            for c in ("代码", "股票代码", "code"):
                                if c in dfc.columns:
                                    code_c = c
                                    break
                            if code_c:
                                keep_codes.update(dfc[code_c].astype(str).tolist())
                        except Exception:
                            continue
                    if keep_codes:
                        df = df[df["code"].astype(str).isin(keep_codes)]
                        mainline_applied = True
            except Exception:
                mainline_applied = False
        # If still not applied, keep df as-is (真实数据不足以筛主线时不造规则)
    # Return structured entries so downstream can carry industry labels
    out: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        out.append({
            "code": str(r["code"]),
            "industry": (str(r["行业"]) if "行业" in df.columns and pd.notna(r.get("行业")) else None),
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


def generate_candidates(symbols: List[str] | None, env_grade: str, topk: int = 3) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    cfg = load_config()
    hub = MarketDataHub()
    pool: List[Dict[str, Any]] = []
    veto_reasons = []
    # Build base symbols dynamically when not provided
    base_entries = ([{"code": s} for s in symbols] if symbols else _build_dynamic_universe_symbols())
    for entry in base_entries:
        sym = entry.get("code")
        df, _ = hub.daily_ohlcv(sym, None, min_len=250)
        feat = compute_indicators(df)
        # facts
        last = feat.iloc[-1]
        avg5_amount = float(feat["amount_5d_avg"].iloc[-1]) if not pd.isna(feat["amount_5d_avg"].iloc[-1]) else 0.0
        atrp = float(last["atr_pct"]) if not pd.isna(last["atr_pct"]) else 0.0
        gap = float(last["gap_pct"]) if not pd.isna(last["gap_pct"]) else 0.0
        close = float(last["close"]) if not pd.isna(last["close"]) else 0.0
        ma20 = float(last["ma20"]) if not pd.isna(last["ma20"]) else 0.0
        # pressure flags
        pressure = {"near_ma20": bool(ma20 and abs((close - ma20) / ma20) <= 0.005)}
        # chip
        chip, chip_meta = compute_chip(feat)
        q_grade = grade_noise(feat, env_grade)

        cand = {
            "symbol": sym,
            "name": entry.get("name"),
            "industry": entry.get("industry"),
            "source_reason": "默认候选池",
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
        # One-vote veto and observe flags / hard filters
        observe_only = False
        reasons: List[str] = []
        # Hard filter: insufficient liquidity by 5d amount
        if avg5_amount < cfg.min_avg_amount:
            veto_reasons.append({"symbol": sym, "reason": "LOW_LIQ_HARD", "amount_5d_avg": avg5_amount})
            continue
        if cand["liquidity"]["grade"] == "C":
            observe_only = True
            reasons.append("流动性C：仅观察仓")
        if atrp > 0.08:
            observe_only = True
            reasons.append("ATR%>8%：仅观察/降仓")
        if gap > 0.02:
            observe_only = True
            reasons.append("Gap>+2%：当日禁买")
        if chip.dist_to_90_high_pct <= 0.02:
            observe_only = True
            reasons.append("贴近筹码90%上限：当日禁买")
        cand["flags"] = {"must_observe_only": bool(observe_only), "reasons": reasons}
        pool.append(cand)
    # rank by simple slope20 then by lower ATR and liquidity grade
    pool.sort(key=lambda x: (-(x["indicators"]["slope20"] or 0.0), x["atr_pct"], x["liquidity"]["grade"]))
    return pool, veto_reasons
