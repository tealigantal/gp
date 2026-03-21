from __future__ import annotations

"""
Deterministic handlers for finance-specific intents (Phase 1).

Guarantees:
 - Never ask LLM to generate entry/stop/take/RR/actionable/execution_state
 - Use cached data or engine outputs; degrade with friendly messages
"""

from typing import Any, Dict, List, Optional, Tuple
import re

import pandas as pd

from ..recommend.datahub import MarketDataHub
from . import session_store as store
from .slot_resolver import resolve_targets
from .refresh_service import refresh_symbols

try:  # thresholds aligned with engine when available
    from ..recommend.agent import (
        MIN_RR_FOR_ACTIONABLE as _MIN_RR,
        EXEC_ACTIONABLE_MAX_GAP_PCT as _ACT_GAP,
        EXEC_WAITING_MAX_GAP_PCT as _WAIT_GAP,
        EXEC_BELOW_SUPPORT_TOL_PCT as _BELOW_TOL,
    )
except Exception:  # pragma: no cover - fallback constants
    _MIN_RR = 0.3
    _ACT_GAP = 0.03
    _WAIT_GAP = 0.08
    _BELOW_TOL = -0.005


def _compute_fallback_bands(df: pd.DataFrame) -> Dict[str, float]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    x = df.tail(120).reset_index(drop=True)
    # ATR14 fallback
    def tr_at(i: int) -> float:
        if i == 0:
            return float(x.loc[i, "high"] - x.loc[i, "low"])  # type: ignore[index]
        prev = x.loc[i - 1, "close"]  # type: ignore[index]
        hi = float(x.loc[i, "high"])  # type: ignore[index]
        lo = float(x.loc[i, "low"])   # type: ignore[index]
        return max(hi - lo, abs(hi - float(prev)), abs(lo - float(prev)))

    atr = pd.Series([tr_at(i) for i in range(len(x))]).ewm(alpha=1.0 / 14.0, adjust=False).mean().iloc[-1]
    c = float(x.loc[len(x) - 1, "close"])  # type: ignore[index]
    return {"S1": round(c - float(atr), 2), "S2": round(c - 2.0 * float(atr), 2), "R1": round(c + float(atr), 2), "R2": round(c + 2.0 * float(atr), 2)}


def _bands_from_last_pick(session_id: str, symbol: str) -> Dict[str, float]:
    last = store.load_last_recommend(session_id) or {}
    for p in (last.get("picks") or []):
        try:
            if str((p or {}).get("symbol") or "").strip() != symbol:
                continue
            tp = (p or {}).get("trade_plan") or {}
            b = (tp or {}).get("bands") or {}
            if all(k in b for k in ("S1", "S2", "R1", "R2")):
                return {"S1": float(b.get("S1", 0.0)), "S2": float(b.get("S2", 0.0)), "R1": float(b.get("R1", 0.0)), "R2": float(b.get("R2", 0.0))}
        except Exception:
            continue
    return {}


def _latest_close(symbol: str) -> Optional[float]:
    hub = MarketDataHub()
    try:
        df, _meta = hub.daily_ohlcv(symbol, as_of=None, min_len=0, prefer_cache_only=True)
        if isinstance(df, pd.DataFrame) and not df.empty:
            return float(df.iloc[-1]["close"])  # type: ignore[index]
    except Exception:
        pass
    # Dev/fixture fallback (no network)
    try:
        from ..dev.fixtures import dev_ohlcv_bars  # type: ignore

        bars, _m = dev_ohlcv_bars(symbol, as_of=None, limit=2)
        if bars:
            return float(bars[-1].get("close"))
    except Exception:
        pass
    return None


def assess_rr(session_id: str, message: str) -> Dict[str, Any]:
    """Assess RR and actionability for the current/focused symbol deterministically."""
    target = resolve_targets(session_id, message)
    if target.get("kind") != "symbol":
        return {
            "ok": False,
            "message": "需要明确单一标的：可输入代码/名称；如基于推荐，支持‘第几只/这只’等指代",
            "code": "NO_SYMBOL",
        }
    symbol = str(target.get("symbol"))
    # Prefer bands from last pick; fallback to ATR bands from cached bars
    bands = _bands_from_last_pick(session_id, symbol)
    close = _latest_close(symbol)
    hub = MarketDataHub()
    if not bands or close is None:
        try:
            df, _m = hub.daily_ohlcv(symbol, as_of=None, min_len=0, prefer_cache_only=True)
            if isinstance(df, pd.DataFrame) and not df.empty:
                if not bands:
                    bands = _compute_fallback_bands(df)
                if close is None:
                    close = float(df.iloc[-1]["close"])  # type: ignore[index]
        except Exception:
            pass
    if not bands or close is None:
        return {"ok": False, "message": "数据不足，暂无法评估盈亏比", "code": "DATA_UNAVAILABLE"}

    s1 = float(bands.get("S1", 0.0))
    r1 = float(bands.get("R1", 0.0))
    rr = None
    signed_gap = None
    state = "observe_only"
    actionable = False
    try:
        if close and s1:
            signed_gap = (close - s1) / close
        if close and s1 and r1 and close > s1:
            rr = float((r1 - close) / max(1e-6, (close - s1)))
        # decide state using signed gap and RR
        if signed_gap is None:
            state = "observe_only"; actionable = False
        else:
            if signed_gap <= _BELOW_TOL:
                state = "below_support"; actionable = False
            elif signed_gap <= 0.0:
                state = "breakdown_risk"; actionable = False
            elif abs(signed_gap) <= _ACT_GAP:
                if rr is None or rr < _MIN_RR:
                    state = "observe_only"; actionable = False
                else:
                    state = "actionable"; actionable = True
            elif abs(signed_gap) <= _WAIT_GAP:
                state = "waiting_pullback"; actionable = False
            else:
                state = "observe_only"; actionable = False
    except Exception:
        pass

    def _fmt(x: Optional[float], pct: bool = False) -> str:
        if x is None:
            return "-"
        v = float(x)
        return (f"{v:.2%}" if pct else f"{v:.2f}")

    summary = [
        f"标的：{symbol}",
        f"价格：{_fmt(close)}  关键带：S1={_fmt(s1)} R1={_fmt(r1)}",
        f"入场偏离：{_fmt(signed_gap, pct=True)}  盈亏比：{_fmt(rr)}",
        f"结论：{'可执行' if actionable else '仅观察'}（状态：{state}）",
    ]
    return {"ok": True, "message": "\n".join(summary), "symbol": symbol, "rr": rr, "actionable": actionable, "state": state}


def _ordinal_pairs(message: str) -> Optional[Tuple[int, int]]:
    s = (message or "")
    # patterns like: 第二只和第一只 / 第2只和第1只 / 第2个和第1个
    m = re.search(r"第\s*(\d+)\s*(?:只|个).{0,4}?第\s*(\d+)\s*(?:只|个)", s)
    if m:
        try:
            a = int(m.group(1)); b = int(m.group(2))
            if a >= 1 and b >= 1:
                return a, b
        except Exception:
            return None
    # textual ordinals
    repl = s.replace("第一", "第1").replace("第二", "第2").replace("第三", "第3")
    m2 = re.search(r"第\s*(\d)\s*(?:只|个).{0,4}?和.{0,4}?第\s*(\d)\s*(?:只|个)", repl)
    if m2:
        try:
            return int(m2.group(1)), int(m2.group(2))
        except Exception:
            return None
    return None


def compare_symbols(session_id: str, message: str) -> Dict[str, Any]:
    st = store.get_state(session_id)
    active = list(st.get("active_symbols") or [])
    last_syms = active or list(st.get("last_recommend_symbols") or [])
    syms: List[str] = []
    pr = _ordinal_pairs(message)
    if pr and len(last_syms) >= max(pr[0], pr[1]):
        syms = [last_syms[pr[0] - 1], last_syms[pr[1] - 1]]
    else:
        tgt = resolve_targets(session_id, message)
        if tgt.get("kind") == "collection":
            syms = list(tgt.get("symbols") or [])
        elif tgt.get("kind") == "symbol":
            # require at least 2 to compare; try pair with focused if available but avoid default-first
            focus = store.get_focus(session_id)
            if focus and focus != tgt.get("symbol"):
                syms = [str(tgt.get("symbol")), str(focus)]
        if not syms:
            syms = list(last_syms[:3])
    syms = [s for s in syms if s]
    syms = list(dict.fromkeys(syms))  # dedup, keep order
    if len(syms) < 2:
        return {"ok": False, "message": "需要至少两只标的进行比较。可使用‘第二只和第一只’或‘这三只哪个好’。", "code": "NEED_TWO"}

    # Compare using last recommendation champion score when available
    last = store.load_last_recommend(session_id) or {}
    picks = (last.get("picks") or []) if isinstance(last, dict) else []
    score_by_sym: Dict[str, float] = {}
    for s in syms:
        for p in picks:
            try:
                if str((p or {}).get("symbol") or "").strip() != s:
                    continue
                champ = (p or {}).get("champion") or {}
                sc = champ.get("score")
                if isinstance(sc, (int, float)):
                    score_by_sym[s] = float(sc)
                break
            except Exception:
                continue

    sorted_syms = sorted(syms, key=lambda x: score_by_sym.get(x, float("nan")), reverse=True)
    lines = ["比较：" + " vs ".join(syms)]
    for s in sorted_syms:
        sc = score_by_sym.get(s)
        lines.append(f"- {s}：分数 {('%.2f' % sc) if isinstance(sc, (int, float)) else '未知'}")
    best = sorted_syms[0]
    reason = "基于最近推荐评分" if any(isinstance(v, float) for v in score_by_sym.values()) else "基于当前上下文顺序"
    lines.append(f"结论：{best} 更优（{reason}）")
    # remember compare symbols
    try:
        store.set_compare_symbols(session_id, syms)
    except Exception:
        pass
    return {"ok": True, "message": "\n".join(lines), "symbols": syms, "best": best}


def ask_no_trade_reason(session_id: str, _message: str) -> Dict[str, Any]:
    last = store.load_last_recommend(session_id)
    if not last:
        return {"ok": False, "message": "还没有推荐记录。可先输入：给我推荐3只"}
    debug = (last or {}).get("debug") or {}
    ds = (last or {}).get("data_status") or {}
    degraded = bool((debug or {}).get("degraded") is True)
    tradeable = (last or {}).get("tradeable")
    reasons = []
    try:
        reasons = [str(r.get("reason_code")) for r in (debug.get("degrade_reasons") or []) if isinstance(r, dict)]
    except Exception:
        reasons = []
    msg = []
    if tradeable is False:
        msg.append("今日不建议买入：交易环境或候选不满足条件。")
    elif not (last.get("picks") or []):
        msg.append("今日暂无合适标的：候选为空或被过滤。")
    else:
        msg.append("建议以观察为主：执行条件未满足。")
    if degraded:
        msg.append("数据仍可用，但部分来源降级，已采用保守策略。")
    if reasons:
        msg.append("内部诊断：" + ",".join(sorted(set(reasons))) )
    return {"ok": True, "message": "\n".join(msg)}


def refresh_trade_plan(session_id: str, message: str) -> Dict[str, Any]:
    tgt = resolve_targets(session_id, message)
    symbols: List[str] = []
    if tgt.get("kind") == "collection":
        symbols = [str(s) for s in (tgt.get("symbols") or []) if str(s)]
    elif tgt.get("kind") == "symbol":
        symbols = [str(tgt.get("symbol"))]
    else:
        st = store.get_state(session_id)
        symbols = list(st.get("active_symbols") or []) or list(st.get("last_recommend_symbols") or [])
    symbols = list(dict.fromkeys([s for s in symbols if s]))
    if not symbols:
        return {"ok": False, "message": "需要明确标的集合，可输入：这三只都重新算 / 第二只 / 600519"}
    out = refresh_symbols(symbols)
    if not out.get("ok"):
        return {"ok": False, "message": "刷新失败，已记录。稍后再试。"}
    # Persist active run context and last recommend symbols
    try:
        store.set_active_run(session_id, out.get("run_id"), symbols)
        # best-effort: align last_recommend_symbols for later ordinals
        sr = {"as_of": out.get("as_of"), "picks": out.get("picks") or []}
        store.set_last_recommend_and_symbols(session_id, sr)
        store.set_last_refresh(session_id)
        store.set_last_intent(session_id, "refresh_trade_plan", message_type="text")
    except Exception:
        pass
    return {
        "ok": True,
        "message": f"已按最新数据重算：{', '.join(symbols)}",
        "run_id": out.get("run_id"),
        "symbols": symbols,
        "picks": out.get("picks") or [],
        "degraded": (out.get("diagnostics") or {}).get("degraded"),
    }


def exit_decision(session_id: str, message: str) -> Dict[str, Any]:
    """Decide exit action deterministically based on structure data.

    Output action in {HOLD, REDUCE, SELL, WATCH}.
    Consider: invalidation, below key bands, RR deterioration after TP1, time-stop 1–3 days window.
    """
    tgt = resolve_targets(session_id, message)
    symbol: Optional[str] = None
    if tgt.get("kind") == "symbol":
        symbol = str(tgt.get("symbol"))
    else:
        # inherit focus if available
        focus = store.get_focus(session_id)
        if focus:
            symbol = str(focus)
    if not symbol:
        return {"ok": False, "message": "需要明确标的，可输入代码/名称或使用‘这只’/‘第几只’", "code": "NO_SYMBOL"}
    # Gather minimal context
    bands = _bands_from_last_pick(session_id, symbol)
    close = _latest_close(symbol)
    decision = "WATCH"
    reasons: List[str] = []

    # 1) Below key band => SELL
    try:
        s1 = float(bands.get("S1")) if bands and bands.get("S1") is not None else None  # type: ignore[arg-type]
    except Exception:
        s1 = None
    if close is not None and s1 is not None and close < s1:
        decision = "SELL"; reasons.append("跌破关键支撑S1")

    # 2) Use pick details if active run available
    try:
        from ..kernel.facade import get_pick_detail as _pick_detail, get_gated_artifact_v2 as _get_art
        st = store.get_state(session_id)
        run_id = st.get("active_run_id")
        it = None
        art_as_of = None
        if run_id:
            det = _pick_detail(run_id, symbol)
            if det.get("ok"):
                it = (det.get("item") or {})
            art = _get_art(run_id=run_id)
            art_as_of = art.get("as_of")
        # invalidation
        inv_now = None
        try:
            inv_now = bool(it.get("invalidated_now")) if isinstance(it, dict) else None
        except Exception:
            inv_now = None
        if inv_now:
            decision = "SELL"; reasons.append("失效条件触发")
        # execution state
        try:
            state = str(it.get("execution_state") or "") if isinstance(it, dict) else ""
            if state == "below_support" and "SELL" not in decision:
                decision = "SELL"; reasons.append("状态：跌破支撑")
        except Exception:
            pass
        # TP1 reached + RR deteriorated
        try:
            tp = (it.get("take_profit") or []) if isinstance(it, dict) else []
            rr = float(it.get("reward_risk")) if isinstance(it, dict) and it.get("reward_risk") is not None else None
            if close is not None and isinstance(tp, list) and tp:
                tp1 = float(tp[0]) if tp[0] is not None else None
                if tp1 is not None and close >= tp1 and (rr is None or rr < 0.6):
                    # prefer reduce first when profits likely taken
                    if decision != "SELL":
                        decision = "REDUCE"
                        reasons.append("达成一目标且RR下降")
        except Exception:
            pass
        # time-stop window (as_of older than 3 days)
        try:
            if art_as_of:
                import datetime as _dt
                y, m, d = [int(x) for x in str(art_as_of).replace('-', '')[:8].split('') if False]  # placeholder to satisfy linter
        except Exception:
            pass
        try:
            if art_as_of and isinstance(art_as_of, str):
                s = art_as_of.replace('-', '')
                if len(s) >= 8 and s[:8].isdigit():
                    y = int(s[:4]); m = int(s[4:6]); d = int(s[6:8])
                    from datetime import date as _date
                    dt_asof = _date(y, m, d)
                    today = _date.today()
                    days = (today - dt_asof).days
                    if days >= 3 and decision not in {"SELL", "REDUCE"}:
                        decision = "SELL"
                        reasons.append("超出1-3日窗口")
        except Exception:
            pass
    except Exception:
        pass

    # 3) Default if actionable and no sell cues => HOLD
    if decision == "WATCH":
        # If we can infer actionable from last pick trade plan or bands proximity
        try:
            if close is not None and s1 is not None and 0 <= (close - s1) / max(close, 1e-6) <= _ACT_GAP:
                decision = "HOLD"; reasons.append("仍在可执行带附近")
        except Exception:
            pass

    # sanitize final
    if decision not in {"HOLD", "REDUCE", "SELL", "WATCH"}:
        decision = "WATCH"

    return {"ok": True, "symbol": symbol, "decision": decision, "reasons": reasons}
