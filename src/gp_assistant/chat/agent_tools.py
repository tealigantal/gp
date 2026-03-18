from __future__ import annotations

"""
Agent tool layer for chat orchestration.

Provides a constrained, deterministic toolset that the chat agent can call.
Each tool exposes: name, description, args_schema, and a run(args, state) -> ToolResult.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from ..core.types import ToolResult
from ..recommend.datahub import MarketDataHub
from ..recommend.runner import run as recommend_run
from ..tools.registry import Tool, ToolRegistry
from ..tools.explain import run_explain as _run_explain
from ..tools.signals import compute_indicators
from . import session_store as store


@dataclass
class ToolCall:
    name: str
    args: Dict[str, Any]
    ok: bool
    message: str
    summary: Dict[str, Any]


def _ok(message: str, data: Any | None = None) -> ToolResult:
    return ToolResult(ok=True, message=message, data=data)


def _err(message: str, *, code: str = "error", detail: Dict[str, Any] | None = None) -> ToolResult:
    return ToolResult(ok=False, message=message, data={"error_code": code, "detail": detail or {}})


# ---------------- Session tools ----------------


def t_get_session_history(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    limit = int(args.get("limit", 20))
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    hist = store.load_history(sid, limit=limit)
    return _ok("history_loaded", {"items": hist[-limit:]})


def t_get_last_recommend(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    last = store.load_last_recommend(sid)
    if not last:
        return _err("no_last_recommend", code="NO_RECOMMEND")
    picks = (last or {}).get("picks") or []
    syms = [str((p or {}).get("symbol") or "").strip() for p in picks if isinstance(p, dict)]
    return _ok("last_recommend_loaded", {"picks": picks, "symbols": [s for s in syms if s]})


def t_get_session_focus(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    st = store.get_state(sid)
    return _ok("focus_loaded", {"symbol": st.get("current_focus_symbol"), "name": st.get("current_focus_name")})


def t_set_session_focus(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    sym = str(args.get("symbol", "")).strip()
    reason = str(args.get("reason", "")).strip() or None
    name = str(args.get("name", "")).strip() or None
    if not sid or not sym:
        return _err("missing session_id or symbol", code="MISSING_ARG")
    st = store.set_focus(sid, sym, reason=reason, name=name)
    return _ok("focus_set", {"state": st})


def t_get_last_symbols(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    syms = store.get_last_symbols(sid)
    return _ok("last_symbols_loaded", {"symbols": syms})


# ---------------- Symbol resolution ----------------


_RE_CODE = re.compile(r"\b(\d{6})(?:\.(?:SZ|SH))?\b", re.IGNORECASE)


def _match_name_in_picks(message: str, picks: list[dict]) -> Optional[Tuple[str, str]]:
    s = (message or "").lower()
    for p in picks or []:
        try:
            name = str((p or {}).get("name") or "").strip()
            sym = str((p or {}).get("symbol") or "").strip()
            if name and sym and name.lower() in s:
                return sym, f"matched_name:{name}"
        except Exception:
            continue
    return None


def _ordinal_n_from_text(message: str) -> Optional[int]:
    s = (message or "")
    if any(k in s for k in ["第一只", "第一个", "第1只", "第1个", "first"]):
        return 1
    if any(k in s for k in ["第二只", "第二个", "第2只", "第2个", "second"]):
        return 2
    if any(k in s for k in ["第三只", "第三个", "第3只", "第3个", "third"]):
        return 3
    return None


def t_resolve_symbol_from_message(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    msg = str(args.get("message", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")

    candidates: list[Tuple[str, str]] = []  # (symbol, reason)

    # 1) direct 6-digit code
    m = _RE_CODE.findall(msg)
    if m:
        # deterministic: pick the first occurrence
        return _ok("resolved_direct_code", {"symbol": m[0], "reason": "direct_code"})

    # 2) ordinal from last recommend symbols
    syms = store.get_last_symbols(sid)
    n = _ordinal_n_from_text(msg)
    if n is not None:
        if not syms or len(syms) < n:
            return _err("ordinal_out_of_range", code="ORDINAL_OUT_OF_RANGE", detail={"n": n, "available": syms})
        return _ok("resolved_ordinal", {"symbol": syms[n - 1], "reason": f"ordinal_{n}"})

    # 3) pronoun resolution based on focus only (no default-first)
    pronouns = ["这只", "这票", "刚才那只", "上一只", "那只", "这一个", "这个", "它"]
    if any(k in msg for k in pronouns):
        focus = store.get_focus(sid)
        if focus:
            return _ok("resolved_focus", {"symbol": focus, "reason": "pronoun_focus"})
        return _err("pronoun_but_no_context", code="AMBIGUOUS", detail={"candidates": []})

    # 4) name matching within last picks
    last = store.load_last_recommend(sid)
    if last and isinstance(last, dict):
        p = _match_name_in_picks(msg, (last or {}).get("picks") or [])
        if p is not None:
            return _ok("resolved_name_match", {"symbol": p[0], "reason": p[1]})

    # 5) explicit requirement to specify symbol for analysis when ambiguous
    if any(k in msg for k in ["研究", "K线", "日线", "买卖点", "支撑", "阻力", "止损", "止盈"]):
        return _err("no_symbol_context", code="NO_CONTEXT")

    return _err("unable_to_resolve_symbol", code="NO_MATCH")


def t_resolve_ordinal_symbol(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    n = int(args.get("ordinal", 1))
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    if n < 1:
        return _err("invalid ordinal", code="INVALID_ARG", detail={"ordinal": n})
    syms = store.get_last_symbols(sid)
    if not syms or len(syms) < n:
        return _err("ordinal_out_of_range", code="ORDINAL_OUT_OF_RANGE", detail={"n": n, "available": syms})
    return _ok("resolved_ordinal", {"symbol": syms[n - 1], "reason": f"ordinal_{n}"})


def t_resolve_focus_or_default(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    focus = store.get_focus(sid)
    if focus:
        return _ok("focus_symbol", {"symbol": focus, "reason": "focus"})
    return _err("no_symbol_context", code="NO_CONTEXT")


# ---------------- Market data tools ----------------


def t_get_ohlcv(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    as_of = args.get("as_of")
    limit = int(args.get("limit", 120))
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    hub = MarketDataHub()
    try:
        # Avoid network in agent path; prefer cache and fallback fixtures
        df, meta = hub.daily_ohlcv(symbol, as_of=as_of, min_len=0, prefer_cache_only=True)
        if isinstance(df, pd.DataFrame) and limit > 0:
            df = df.tail(limit)
        rows = [
            {
                "date": pd.to_datetime(r["date"]).date().isoformat(),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0.0) or 0.0),
                "amount": float(r.get("amount", 0.0) or 0.0),
            }
            for _, r in df.reset_index(drop=True).iterrows()
        ]
        # Fallback to dev fixture bars if empty
        if not rows:
            try:
                from ..dev.fixtures import dev_ohlcv_bars  # type: ignore

                bars, meta2 = dev_ohlcv_bars(symbol, as_of=as_of, limit=limit)
                return _ok("ohlcv_loaded_dev", {"symbol": symbol, "meta": meta2, "bars": bars})
            except Exception:
                pass
        return _ok("ohlcv_loaded", {"symbol": symbol, "meta": meta, "bars": rows})
    except Exception as e:  # noqa: BLE001
        # Fallback to dev fixture
        try:
            from ..dev.fixtures import dev_ohlcv_bars  # type: ignore

            bars, meta2 = dev_ohlcv_bars(symbol, as_of=as_of, limit=limit)
            return _ok("ohlcv_loaded_dev", {"symbol": symbol, "meta": meta2, "bars": bars})
        except Exception:
            return _err(f"ohlcv_failed: {e}", code="DATA_UNAVAILABLE")


def t_get_recent_bars(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    # alias for get_ohlcv with n
    n = int(args.get("n", 60))
    payload = dict(args)
    payload.pop("n", None)
    payload["limit"] = n
    return t_get_ohlcv(payload, _state)


def t_get_latest_price_snapshot(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    hub = MarketDataHub()
    try:
        df, meta = hub.daily_ohlcv(symbol, as_of=None, min_len=0, prefer_cache_only=True)
        if len(df) == 0:
            return _err("no_bars", code="EMPTY")
        last = df.iloc[-1]
        return _ok("latest_snapshot", {"symbol": symbol, "date": str(pd.to_datetime(last["date"]).date()), "close": float(last["close"])})
    except Exception as e:  # noqa: BLE001
        return _err(f"snapshot_failed: {e}", code="DATA_UNAVAILABLE")


# ---------------- Recommend/analysis tools ----------------


def t_rerun_recommend(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    topk = int(args.get("topk", 3))
    as_of = args.get("as_of")
    mode = args.get("mode")
    try:
        res = recommend_run(mode=mode, date=as_of, topk=topk)
        return _ok("recommend_rerun", {"result": res})
    except Exception as e:  # noqa: BLE001
        return _err(f"recommend_failed: {e}", code="RECOMMEND_ERROR")


def t_recompute_trade_plan(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    as_of = args.get("as_of")
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    try:
        res = recommend_run(symbols=[symbol], date=as_of, topk=1)
        # extract the pick for symbol
        pick = None
        picks = (res or {}).get("picks") or []
        for p in picks:
            if str((p or {}).get("symbol") or "").strip() == symbol:
                pick = p
                break
        return _ok("trade_plan", {"symbol": symbol, "pick": pick, "result": res})
    except Exception as e:  # noqa: BLE001
        return _err(f"tradeplan_failed: {e}", code="RECOMMEND_ERROR")


def t_explain_pick(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    session_id = str(args.get("session_id", "")).strip()
    as_of = args.get("as_of")
    pick = None
    if session_id:
        last = store.load_last_recommend(session_id)
        ps = (last or {}).get("picks") or []
        for p in ps:
            if str((p or {}).get("symbol") or "").strip() == symbol:
                pick = p
                break
    if pick is None:
        r = t_recompute_trade_plan({"symbol": symbol, "as_of": as_of}, _state)
        if not r.ok or not isinstance(r.data, dict):
            return r
        pick = (r.data or {}).get("pick")
    if not pick:
        return _err("no_pick_to_explain", code="NO_PICK")
    return _run_explain({"pick": pick}, _state)


def _compute_key_bands_from_bars(df: pd.DataFrame) -> Dict[str, float]:
    # Simple ATR-based fallback bands
    df2 = df.copy()
    # ATR14
    def _true_range(row):
        i = row.name
        if i == 0:
            return float(row["high"] - row["low"])
        prev = df2.iloc[i - 1]
        return max(
            float(row["high"] - row["low"]),
            abs(float(row["high"] - prev["close"])),
            abs(float(row["low"] - prev["close"]))
        )
    tr = [
        _true_range(df2.iloc[i]) for i in range(len(df2))
    ]
    atr = pd.Series(tr).ewm(alpha=1.0 / 14.0, adjust=False).mean().iloc[-1]
    c = float(df2["close"].iloc[-1])
    s1 = round(c - 1.0 * float(atr), 2)
    s2 = round(c - 2.0 * float(atr), 2)
    r1 = round(c + 1.0 * float(atr), 2)
    r2 = round(c + 2.0 * float(atr), 2)
    return {"S1": s1, "S2": s2, "R1": r1, "R2": r2}


def t_get_key_bands(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    # Try to get from last pick or recompute
    pick = None
    session_id = args.get("session_id")
    if session_id:
        last = store.load_last_recommend(str(session_id))
        for p in (last or {}).get("picks") or []:
            if str((p or {}).get("symbol") or "").strip() == symbol:
                pick = p
                break
    if pick:
        tp = (pick or {}).get("trade_plan") or {}
        bands = (tp or {}).get("bands") or {}
        if all(k in bands for k in ["S1", "S2", "R1", "R2"]):
            return _ok("bands_from_pick", {"symbol": symbol, "bands": bands, "source": "pick"})
    # Fallback compute from bars
    r = t_get_ohlcv({"symbol": symbol, "limit": 120}, _state)
    if not r.ok:
        return r
    bars = ((r.data or {}) if isinstance(r.data, dict) else {}).get("bars") or []
    if not bars:
        return _err("no_bars", code="EMPTY")
    df = pd.DataFrame(bars)
    bands = _compute_key_bands_from_bars(df)
    return _ok("bands_from_bars", {"symbol": symbol, "bands": bands, "source": "atr14"})


def t_get_trade_plan_summary(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    as_of = args.get("as_of")
    heavy = bool(args.get("heavy", False))
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    if heavy:
        r = t_recompute_trade_plan({"symbol": symbol, "as_of": as_of}, _state)
        if not r.ok:
            return r
        pick = (r.data or {}).get("pick") if isinstance(r.data, dict) else None
        bands = ((pick or {}).get("trade_plan") or {}).get("bands") if isinstance(pick, dict) else None
        if not bands:
            # fallback to light summary
            heavy = False
        else:
            return _ok("trade_plan_summary", {"symbol": symbol, "bands": bands, "heavy": True})
    # light summary
    r2 = t_get_key_bands({"symbol": symbol}, _state)
    if not r2.ok:
        return r2
    return _ok("trade_plan_summary", {"symbol": symbol, "bands": (r2.data or {}).get("bands"), "heavy": False})


def t_get_strategy_context(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    as_of = args.get("as_of")
    limit = int(args.get("limit", 180))
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    r = t_get_ohlcv({"symbol": symbol, "as_of": as_of, "limit": limit}, _state)
    if not r.ok:
        return r
    bars = ((r.data or {}) if isinstance(r.data, dict) else {}).get("bars") or []
    if not bars:
        return _err("no_bars", code="EMPTY")
    df = pd.DataFrame(bars)
    feat = compute_indicators(df)
    last = feat.iloc[-1]
    out = {
        "atr_pct": float(last.get("atr_pct", 0.0) or 0.0),
        "rsi2": float(last.get("rsi2", 0.0) or 0.0),
        "bias6": float(last.get("bias6", 0.0) or 0.0),
        "bias12": float(last.get("bias12", 0.0) or 0.0),
        "bbwidth20": float(last.get("bbwidth20", 0.0) or 0.0),
        "insufficient_history": bool(last.get("insufficient_history", False)),
    }
    return _ok("strategy_context", out)


def t_get_chart_context(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    limit = int(args.get("limit", 120))
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    r = t_get_ohlcv({"symbol": symbol, "limit": limit}, _state)
    if not r.ok:
        return r
    bars = ((r.data or {}) if isinstance(r.data, dict) else {}).get("bars") or []
    if not bars:
        return _err("no_bars", code="EMPTY")
    df = pd.DataFrame(bars)
    feat = compute_indicators(df)
    # include a compact slice for chart overlay
    sel = feat[[c for c in feat.columns if c in {"date", "close", "ma5", "ma10", "ma20", "ma60"}]]
    rows = [
        {**{"date": str(pd.to_datetime(r["date"]).date())}, **{k: float(r.get(k)) for k in r.index if k != "date" and pd.notna(r.get(k))}}
        for _, r in sel.reset_index(drop=True).iterrows()
    ]
    return _ok("chart_context", {"symbol": symbol, "bars": rows})


def t_get_support_resistance_summary(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return _err("missing symbol", code="MISSING_ARG")
    r = t_get_ohlcv({"symbol": symbol, "limit": 180}, _state)
    if not r.ok:
        return r
    bars = ((r.data or {}) if isinstance(r.data, dict) else {}).get("bars") or []
    if not bars:
        return _err("no_bars", code="EMPTY")
    df = pd.DataFrame(bars)
    hi20 = float(df["high"].rolling(20).max().iloc[-1]) if len(df) >= 20 else float("nan")
    lo20 = float(df["low"].rolling(20).min().iloc[-1]) if len(df) >= 20 else float("nan")
    hi60 = float(df["high"].rolling(60).max().iloc[-1]) if len(df) >= 60 else float("nan")
    lo60 = float(df["low"].rolling(60).min().iloc[-1]) if len(df) >= 60 else float("nan")
    last_close = float(df["close"].iloc[-1])
    return _ok(
        "sr_summary",
        {
            "symbol": symbol,
            "last_close": last_close,
            "high20": hi20,
            "low20": lo20,
            "high60": hi60,
            "low60": lo60,
        },
    )


# ---------------- Debug tools ----------------


def t_list_available_tools(args: dict, registry: ToolRegistry) -> ToolResult:  # type: ignore[override]
    items = []
    for name, tool in registry.list().items():
        items.append({"name": name, "description": tool.description, "args_schema": tool.args_schema})
    return _ok("tools_list", {"tools": sorted(items, key=lambda x: x["name"])})


def t_explain_tool_trace(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    st = store.get_state(sid)
    return _ok("tool_trace", {"last_tool_trace": st.get("last_tool_trace")})


def t_explain_agent_trace(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    st = store.get_state(sid)
    return _ok("agent_trace", {"last_agent_trace": st.get("last_agent_trace")})


def t_dump_session_state(args: dict, _state: Any) -> ToolResult:  # noqa: ANN401
    sid = str(args.get("session_id", "")).strip()
    if not sid:
        return _err("missing session_id", code="MISSING_ARG")
    st = store.get_state(sid)
    return _ok("session_state", {"state": st})


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.add(
        Tool(
            name="get_session_history",
            description="Load recent chat history for a session",
            args_schema={"session_id": "str", "limit": "int?"},
            run=t_get_session_history,
        )
    )
    reg.add(
        Tool(
            name="get_last_recommend",
            description="Get last recommendation payload and symbols for a session",
            args_schema={"session_id": "str"},
            run=t_get_last_recommend,
        )
    )
    reg.add(
        Tool(
            name="get_session_focus",
            description="Get current focus symbol for the session",
            args_schema={"session_id": "str"},
            run=t_get_session_focus,
        )
    )
    reg.add(
        Tool(
            name="set_session_focus",
            description="Set session focus to a specific symbol",
            args_schema={"session_id": "str", "symbol": "str", "reason": "str?", "name": "str?"},
            run=t_set_session_focus,
        )
    )
    reg.add(
        Tool(
            name="get_last_symbols",
            description="List symbols from last recommendation, in order",
            args_schema={"session_id": "str"},
            run=t_get_last_symbols,
        )
    )
    reg.add(
        Tool(
            name="resolve_symbol_from_message",
            description="Resolve target symbol from follow-up message using context",
            args_schema={"session_id": "str", "message": "str"},
            run=t_resolve_symbol_from_message,
        )
    )
    reg.add(
        Tool(
            name="resolve_ordinal_symbol",
            description="Resolve nth symbol from last recommendation",
            args_schema={"session_id": "str", "ordinal": "int"},
            run=t_resolve_ordinal_symbol,
        )
    )
    reg.add(
        Tool(
            name="resolve_focus_or_default",
            description="Resolve current focus or default to first symbol",
            args_schema={"session_id": "str"},
            run=t_resolve_focus_or_default,
        )
    )
    # Market data
    reg.add(
        Tool(
            name="get_ohlcv",
            description="Fetch normalized daily OHLCV bars",
            args_schema={"symbol": "str", "as_of": "str?", "limit": "int?"},
            run=t_get_ohlcv,
        )
    )
    reg.add(
        Tool(
            name="get_recent_bars",
            description="Fetch recent N OHLCV bars (alias)",
            args_schema={"symbol": "str", "as_of": "str?", "n": "int?"},
            run=t_get_recent_bars,
        )
    )
    reg.add(
        Tool(
            name="get_latest_price_snapshot",
            description="Get latest close price snapshot from cache",
            args_schema={"symbol": "str"},
            run=t_get_latest_price_snapshot,
        )
    )
    # Recommend/analysis
    reg.add(
        Tool(
            name="rerun_recommend",
            description="Rerun recommendation engine",
            args_schema={"topk": "int?", "as_of": "str?", "mode": "str?"},
            run=t_rerun_recommend,
        )
    )
    reg.add(
        Tool(
            name="recompute_trade_plan",
            description="Recompute trade plan for a symbol via engine",
            args_schema={"symbol": "str", "as_of": "str?"},
            run=t_recompute_trade_plan,
        )
    )
    reg.add(
        Tool(
            name="explain_pick",
            description="Explain why the symbol is picked (context-aware)",
            args_schema={"symbol": "str", "session_id": "str?", "as_of": "str?"},
            run=t_explain_pick,
        )
    )
    reg.add(
        Tool(
            name="get_key_bands",
            description="Get key bands S1/S2/R1/R2 from pick or ATR fallback",
            args_schema={"symbol": "str", "session_id": "str?"},
            run=t_get_key_bands,
        )
    )
    reg.add(
        Tool(
            name="get_strategy_context",
            description="Compute strategy indicators context (ATR%, RSI2, bias, bbwidth)",
            args_schema={"symbol": "str", "as_of": "str?", "limit": "int?"},
            run=t_get_strategy_context,
        )
    )
    reg.add(
        Tool(
            name="get_chart_context",
            description="K-line context with key MAs for chart",
            args_schema={"symbol": "str", "limit": "int?"},
            run=t_get_chart_context,
        )
    )
    reg.add(
        Tool(
            name="get_support_resistance_summary",
            description="Support/resistance summary (20/60 day levels)",
            args_schema={"symbol": "str"},
            run=t_get_support_resistance_summary,
        )
    )
    reg.add(
        Tool(
            name="get_trade_plan_summary",
            description="Summarize trade plan bands; heavy=True triggers recomputation",
            args_schema={"symbol": "str", "as_of": "str?", "heavy": "bool?"},
            run=t_get_trade_plan_summary,
        )
    )
    # Debug
    reg.add(
        Tool(
            name="list_available_tools",
            description="List agent tools",
            args_schema={},
            run=lambda a, _: t_list_available_tools(a, reg),
        )
    )
    reg.add(
        Tool(
            name="explain_tool_trace",
            description="Read last tool trace from session",
            args_schema={"session_id": "str"},
            run=t_explain_tool_trace,
        )
    )
    reg.add(
        Tool(
            name="explain_agent_trace",
            description="Read last agent trace from session",
            args_schema={"session_id": "str"},
            run=t_explain_agent_trace,
        )
    )
    reg.add(
        Tool(
            name="dump_session_state",
            description="Dump structured session state for debugging",
            args_schema={"session_id": "str"},
            run=t_dump_session_state,
        )
    )

    return reg
