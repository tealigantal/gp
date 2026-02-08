# 简介：荐股主引擎。整合市场环境评分、主题池、候选生成、指标与统计、
# 打分与冠军选择，产出 picks 与交易计划，并将结果落盘到 store/recommend。
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from pathlib import Path

import pandas as pd

from ..core.config import load_config
from ..core.paths import store_dir
from .calendar import calendar_summary
from .datahub import MarketDataHub
from .market_env import score_regime
from .theme_pool import build_themes
from .candidate_gen import generate_candidates
from .announcements import fetch_announcements
from .events import future_events
from ..strategy.ts_cv import purged_walk_forward
from ..strategy.event_study import event_study_from_mask
from ..strategy.indicators import compute_indicators
from ..strategy.scoring import score_item
from ..strategy.champion import choose_champion
from ..core.config import load_config


def _make_trade_plan(item: Dict[str, Any], env_grade: str, risk_profile: str) -> Dict[str, Any]:
    inds = item.get("indicators", {})
    chip = item.get("chip", {})
    q = item.get("q_grade")
    ann = item.get("announcement_risk", {})
    ev = item.get("event_risk", {})
    # panel
    panel = {
        "avg5_amount": float(item.get("liquidity", {}).get("avg5_amount", 0.0)),
        "atr_pct": float(inds.get("atr_pct", item.get("atr_pct", 0.0))),
        "gap_pct": float(inds.get("gap_pct", item.get("gap_pct", 0.0))),
        "slope20": float(inds.get("slope20", 0.0)),
    }
    chip_and_bands = {
        "S1": float(chip.get("band_90_low", 0.0)),
        "S2": float(chip.get("avg_cost", 0.0)),
        "R1": float(chip.get("band_90_high", 0.0)),
        "R2": float(chip.get("band_90_high", 0.0)) * 1.02 if chip.get("band_90_high") else 0.0,
        "confidence": chip.get("confidence", "low"),
        "model": chip.get("model_used", "B"),
    }
    bias_stats = {
        "bias6": float(inds.get("bias6", 0.0)) if "bias6" in inds else None,
        "bias12": float(inds.get("bias12", 0.0)) if "bias12" in inds else None,
        "bias6_cross_up": bool(inds.get("bias6_cross_up", False)) if "bias6_cross_up" in inds else False,
    }
    announcements = {"risk_level": ann.get("risk_level", "medium"), "evidence": ann.get("evidence", [])[:2]}
    events = {"event_risk": ev.get("event_risk", "low"), "evidence": ev.get("evidence", [])[:2]}
    window_A = {
        "structure_conditions": [
            "关键带回收且不再创新低",
            "量能衰减或被承接消化",
            "分时重心抬高/横向消化",
        ],
        "confirm_actions": ["仅记录承接≥2项；A窗不追价"],
        "if_not_met": "放弃/观望",
    }
    window_B = {
        "structure_conditions": [
            "收盘前站稳关键结构",
            "回落不破支撑带上沿",
            "尾盘不再大幅二次下砸",
        ],
        "confirm_actions": ["满足≥2项可评估隔夜；仍不追价"],
        "if_not_met": "放弃/观望",
    }
    # risk and position sizing (shares in lots of 100)
    base_shares = 100
    if env_grade == "A" and q in {"Q0", "Q1"} and not item.get("flags", {}).get("must_observe_only", False):
        base_shares = 200 if risk_profile != "conservative" else 100
    if q in {"Q2", "Q3"}:
        base_shares = 100
    risk = {
        "position_shares": base_shares,
        "risk_budget_pct": 1.0 if risk_profile == "aggressive" else (0.7 if risk_profile == "normal" else 0.5),
        "stop_loss": "收盘有效跌破支撑带",
        "time_stop": "第3日不强必走",
        "add_rule": "只允许结构性加仓，禁止摊平亏损",
    }
    invalidation = [
        "放量不涨",
        "频繁冲高回落/长上影",
        "贴近压力带/20日压力/筹码90%上限",
        "命中一票否决（Gap>+2%、公告高风险、ATR%>8%等）",
    ]
    return {
        "panel": panel,
        "q": {"grade": q},
        "chip_and_bands": chip_and_bands,
        "bias_stats": bias_stats,
        "announcements": announcements,
        "events": events,
        "window_A": window_A,
        "window_B": window_B,
        "risk": risk,
        "invalidation": invalidation,
    }


def _write_outputs(as_of: str, payload: Dict[str, Any]) -> None:
    out_dir = store_dir() / "recommend"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{as_of}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # sources/debug already embedded in payload["debug"], write flat versions too
    (out_dir / f"{as_of}_debug.json").write_text(json.dumps(payload.get("debug", {}), ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{as_of}_sources.json").write_text(json.dumps(payload.get("debug", {}).get("sources", []), ensure_ascii=False, indent=2), encoding="utf-8")
    # sources map is included in debug


def run(date: Optional[str] = None, topk: int = 3, universe: str = "auto", symbols: Optional[List[str]] = None, risk_profile: str = "normal") -> Dict[str, Any]:
    cfg = load_config()
    cal = calendar_summary()
    as_of = date or cal["as_of"]
    hub = MarketDataHub()

    env = score_regime(hub)
    themes = build_themes(hub)

    if universe == "symbols" and symbols:
        base = symbols
    else:
        # 严格模式下基于实时快照构建动态候选池，由 candidate_gen 内部实现
        base = None

    pool, veto = generate_candidates(base, env.get("grade", "C"), topk=topk)

    # Prepare benchmark for RS
    try:
        idx_df, _ = hub.index_daily("000300")  # 沪深300
    except Exception:
        idx_df = None

    # Attach announcements/events/statistics and scores
    picks: List[Dict[str, Any]] = []
    for cand in pool:
        sym = cand["symbol"]
        # announcements
        ann = fetch_announcements(sym)
        ev = future_events(sym)

        # stats: CV and event study using bias6 cross up as a simple mask
        # build feature df
        df_feat = None
        try:
            df_feat = pd.DataFrame(cand.get("_df_feat")) if cand.get("_df_feat") is not None else None
        except Exception:
            df_feat = None
        if df_feat is None:
            df, _ = hub.daily_ohlcv(sym, as_of, 250)
            df_feat = compute_indicators(df)
        mask = df_feat.get("bias6_cross_up", pd.Series([False] * len(df_feat)))
        estats = event_study_from_mask(df_feat, mask)
        cv = purged_walk_forward(df_feat, k_folds=5, gap=5)

        # Relative strength vs benchmark (5/20 trading days)
        rs = {"rs5": None, "rs20": None}
        try:
            import pandas as pd
            if idx_df is not None and len(df_feat) >= 25 and len(idx_df) >= 25:
                # align by date
                dfm = df_feat[["date", "close"]].merge(idx_df[["date", "close"]], on="date", suffixes=("_s", "_i"))
                if len(dfm) >= 25:
                    r5_s = float(dfm["close_s"].iloc[-1] / dfm["close_s"].iloc[-6] - 1.0)
                    r5_i = float(dfm["close_i"].iloc[-1] / dfm["close_i"].iloc[-6] - 1.0)
                    r20_s = float(dfm["close_s"].iloc[-1] / dfm["close_s"].iloc[-21] - 1.0)
                    r20_i = float(dfm["close_i"].iloc[-1] / dfm["close_i"].iloc[-21] - 1.0)
                    rs = {"rs5": r5_s - r5_i, "rs20": r20_s - r20_i}
        except Exception:
            pass

        item = {
            **cand,
            "announcement_risk": ann,
            "event_risk": ev,
            "rel_strength": rs,
            "stats": {
                "k": estats.k,
                "win_rate_5": estats.win_rate_5,
                "avg_return_5": estats.mean_return_5,
                "mdd10_avg": estats.mdd10_proxy,
                "sample_warning": estats.sample_warning,
            },
            "strategies": {
                "S1": {"cv": cv.__dict__, "event_study": estats.__dict__},
            },
            "_env": env,
            "_theme_strength": 0.7 if themes else 0.3,
        }
        item["score"] = score_item(item)
        # decorate trade plan
        tp = _make_trade_plan(item, env.get("grade", "C"), risk_profile)
        # attach theme name
        theme_name = themes[0]["name"] if themes else "行业轮动"
        item["theme"] = theme_name
        item["trade_plan"] = tp
        picks.append(item)

    # rank then apply diversification cap per industry/theme
    picks.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    max_per_ind = int(getattr(cfg, "max_per_industry", 2)) if hasattr(cfg, "max_per_industry") else 2
    chosen: list[Dict[str, Any]] = []
    used: dict[str, int] = {}
    for it in picks:
        key = str(it.get("industry") or it.get("theme") or "NA")
        cnt = used.get(key, 0)
        if cnt >= max_per_ind:
            continue
        chosen.append(it)
        used[key] = cnt + 1
        if len(chosen) >= topk:
            break
    picks = chosen

    # champion per pick
    champs = choose_champion(picks)
    for it in picks:
        it["champion"] = champs.get(it["symbol"], {})

    # hard rule: env=D -> empty picks or observe-only
    if env.get("grade") == "D":
        for it in picks:
            it.setdefault("flags", {}).update({"must_observe_only": True})
        picks = []  # keep empty to emphasize 空仓 倾向

    execution_checklist = [
        "1) 环境分层：按指数与成交额口径判断",
        "2) 主线：只做回踩确认，不追价",
        "3) 噪声等级Q：Q2以上A窗禁买，B窗收盘确认",
        "4) 窗口A动作：结构不满足→放弃",
        "5) 窗口B动作：收盘确认决定是否隔夜；第3日硬止损",
    ]

    # sources summary
    sources = [
        {"symbol": it["symbol"], "data_source": "fixtures/provider/synthetic"}
        for it in pool
    ]

    payload = {
        "as_of": as_of,
        "timezone": cfg.timezone,
        "env": env,
        "themes": themes,
        "candidate_pool": pool,
        "picks": picks,
        "execution_checklist": execution_checklist,
        "disclaimer": "本内容仅供研究与教育，不构成任何投资建议或收益承诺；市场有风险，决策需独立承担。",
        "debug": {"timing": {}, "sources": sources, "failures": veto, "cv": {p["symbol"]: p.get("strategies", {}).get("S1", {}).get("cv", {}) for p in picks}},
    }
    _write_outputs(as_of, payload)
    return payload
