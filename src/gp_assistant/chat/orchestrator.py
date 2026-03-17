from __future__ import annotations

"""
Chat Orchestrator (Tool-using Agent)

Routes intents to deterministic tools first, uses LLM to synthesize when helpful,
and degrades gracefully when LLM is unavailable.
Keeps compatibility with existing recommendation flow and event cards.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from . import event_store
from . import session_store as store
from .agent_tools import build_registry
from .intent import detect_intent
from .render import render_recommendation_narrative
from .slot_resolver import resolve_targets
from .finance_intents import assess_rr as _assess_rr, compare_symbols as _compare_symbols, ask_no_trade_reason as _ask_no_trade_reason, refresh_trade_plan as _refresh_trade_plan
from ..llm.client import LLMClient
from ..recommend.compact_payload import compact_recommend_meta
from ..core.paths import store_dir
import json
from ..recommend.runner import run as recommend_run
from ..core.types import ToolResult


def _llm_messages_for_general(hist: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    # History already contains the latest user message; avoid duplicating it.
    sys_prompt = "你是交易研究助理。避免免责声明，直接给出具体看法。"
    return ([{"role": "system", "content": sys_prompt}] + [{"role": h["role"], "content": h["content"]} for h in hist[-6:]])


def _llm_messages_for_followup(hist: List[Dict[str, Any]], gathered: Dict[str, Any]) -> List[Dict[str, str]]:
    sys_prompt = (
        "你是交易研究助理。严禁输出任何‘无法提供投资建议/不构成投资建议/仅供参考’等句式。"
        "当请求K线/买卖点/止损止盈/支撑阻力等分析时，请以提供的工具结果为准，"
        "不要自行编造或推导任何价格、带位、RR、可执行状态，仅做客观描述。"
    )
    return [
        {"role": "system", "content": sys_prompt},
        *[{"role": h["role"], "content": h["content"]} for h in hist[-6:]],
        {"role": "system", "content": f"工具结果: {gathered}"},
    ]


def handle_message(session_id: Optional[str], message: str, message_id: Optional[str] = None) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    store.append_message(sid, "user", message, message_id=message_id)

    intent = detect_intent(message)
    try:
        store.set_last_intent(sid, intent.get("name"), message_type="text")
    except Exception:
        pass
    # Compatibility: robustly accept recommend trigger via simple keyword fallback
    try:
        s_low = (message or "").lower()
        if intent.get("name") != "recommend" and ("latest" in s_low or "recommend" in s_low or ("荐" in message) or ("推荐" in message)):
            intent = {"name": "recommend", "slots": intent.get("slots", {})}
    except Exception:
        pass
    tool_trace: Dict[str, Any] = {"calls": [], "triggered_recommend": False, "recommend_result": None}
    agent_trace: List[Dict[str, Any]] = []
    reply = ""
    degraded = False
    degrade_reason: Optional[str] = None
    resolved_symbol: Optional[str] = None

    if intent["name"] == "recommend":
        try:
            # Optional service mode triggers
            s_msg = (message or "").strip()
            svc_triggers = ["服务荐股", "服务推荐", "最新推荐", "今日推荐", "latest"]
            use_service = any(k.lower() in s_msg.lower() for k in svc_triggers)

            if use_service:
                # Prefer reading from store to avoid runner imports in some environments
                p = store_dir() / "recommend" / "latest.json"
                if p.exists():
                    try:
                        res = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:
                        # fallback to runner service mode
                        res = recommend_run(mode="service", date="latest", topk=int(intent["slots"].get("topk", 3)))
                else:
                    res = recommend_run(mode="service", date="latest", topk=int(intent["slots"].get("topk", 3)))
            else:
                res = recommend_run(topk=int(intent["slots"].get("topk", 3)))
            store.set_last_recommend_and_symbols(sid, res)

            # Avoid duplicating long narrative in thread; prefer card as main artifact
            reply = "已生成推荐清单，请查看卡片。"
            tool_trace = {"triggered_recommend": True, "recommend_result": res}
            agent_trace.append({"step": "recommend", "status": "completed", "topk": int(intent["slots"].get("topk", 3))})

            # Append a recommendation card event
            try:
                picks = res.get("picks") if isinstance(res, dict) else []
                if not isinstance(picks, list):
                    picks = []
                meta = compact_recommend_meta(res if isinstance(res, dict) else {})
                if not isinstance(meta.get("themes"), list):
                    meta["themes"] = []
                eid = f"card-reco-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
                event_store.append_event(
                    sid,
                    event_id=eid,
                    type="message.created",
                    data={
                        "message_id": eid,
                        "kind": "card",
                        "content": "recommendation",
                        "payload": {"type": "recommendation", "picks": picks, "meta": meta},
                    },
                    actor_id="assistant",
                )
            except Exception:
                pass

        except Exception as e:  # noqa: BLE001
            reply = "当前推荐服务暂不可用，已记录错误，稍后再试。"
            tool_trace = {"triggered_recommend": False, "error": str(e)}
            degraded = True
            degrade_reason = f"recommend_failed:{e}"
            # Emit degraded empty card
            try:
                err_payload = {
                    "as_of": datetime.utcnow().strftime("%Y-%m-%d"),
                    "themes": [],
                    "mover_hints": [],
                    "message": f"recommend_error: {e}",
                    "debug": {"degraded": True, "degrade_reasons": [{"reason_code": "RECOMMEND_ERROR", "detail": {"message": str(e)}}]},
                    "data_status": {
                        "snapshot": {"ok": False, "source": None, "rows": 0, "elapsed_sec": None, "cache": "none", "as_of_ts": None, "error": "RECOMMEND_ERROR"},
                        "themes": {"ok": False, "source": None, "attempted": [], "error": "RECOMMEND_ERROR", "as_of_ts": None},
                        "daily": {"ok": False, "symbols_ok": 0, "symbols_fail": 0, "error_summary": "RECOMMEND_ERROR"},
                    },
                }
                meta = compact_recommend_meta(err_payload)
                if not isinstance(meta.get("themes"), list):
                    meta["themes"] = []
                eid = f"card-reco-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
                event_store.append_event(
                    sid,
                    event_id=eid,
                    type="message.created",
                    data={
                        "message_id": eid,
                        "kind": "card",
                        "content": "recommendation",
                        "payload": {"type": "recommendation", "picks": [], "meta": meta},
                    },
                    actor_id="assistant",
                )
            except Exception:
                pass

    elif intent["name"] in {"assess_rr", "compare_symbols", "ask_no_trade_reason", "refresh_trade_plan", "analyze_symbol", "followup_tp", "followup_why", "ask_nth"}:
        # Tool-using / deterministic agent for follow-ups
        reg = build_registry()

        def call(tool: str, args: Dict[str, Any]) -> ToolResult:  # type: ignore[name-defined]
            t = reg.get(tool)
            res = t.run(args, None)
            # summarize in tool trace
            summ: Dict[str, Any] = {"ok": res.ok}
            if isinstance(res.data, dict):
                for k in ["symbol", "reason", "bands", "date", "close", "symbols", "items"]:
                    if k in res.data:
                        summ[k] = res.data[k]
            tool_trace.setdefault("calls", []).append({"tool": tool, "args": args, "message": res.message, "summary": summ})
            return res

        name = intent["name"]
        # Ask-nth routing => analyze
        if name == "ask_nth":
            n = int(intent["slots"].get("n", 1))
            r = call("get_last_symbols", {"session_id": sid})
            if not r.ok:
                degraded = True
                degrade_reason = "no_last_symbols"
                reply = "无法定位第几只，请先进行一次推荐。"
            else:
                syms = (r.data or {}).get("symbols") if isinstance(r.data, dict) else []
                if not syms or len(syms) < n:
                    degraded = True
                    degrade_reason = "ordinal_out_of_range"
                    reply = f"上一轮仅有 {len(syms) if syms else 0} 只标的。"
                else:
                    resolved_symbol = str(syms[n - 1])
                    call("set_session_focus", {"session_id": sid, "symbol": resolved_symbol, "reason": f"ask_nth_{n}"})
                    agent_trace.append({"step": "resolve_symbol", "status": "completed", "symbol": resolved_symbol, "by": f"nth:{n}"})
                    name = "analyze_symbol"
                    intent = {"name": "analyze_symbol", "slots": {}}
        # Deterministic finance intent handlers (no LLM for Phase 1)
        if name == "assess_rr":
            r = _assess_rr(sid, message)
            degraded = not bool(r.get("ok"))
            degrade_reason = None if r.get("ok") else str(r.get("code") or "assess_rr_failed")
            reply = str(r.get("message") or "")
        elif name == "compare_symbols":
            r = _compare_symbols(sid, message)
            degraded = not bool(r.get("ok"))
            degrade_reason = None if r.get("ok") else str(r.get("code") or "compare_failed")
            reply = str(r.get("message") or "")
        elif name == "ask_no_trade_reason":
            r = _ask_no_trade_reason(sid, message)
            degraded = not bool(r.get("ok"))
            reply = str(r.get("message") or "")
        elif name == "refresh_trade_plan":
            r = _refresh_trade_plan(sid, message)
            degraded = not bool(r.get("ok"))
            reply = str(r.get("message") or "")
            tool_trace.setdefault("calls", []).append({"tool": "refresh_trade_plan", "args": {"symbols": r.get("symbols")}, "summary": {"ok": r.get("ok")}})
            # Append a fresh recommendation card with recomputed picks
            if r.get("ok"):
                try:
                    picks = r.get("picks") or []
                    meta = compact_recommend_meta({"as_of": None, "debug": {}})
                    eid = f"card-reco-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
                    event_store.append_event(
                        sid,
                        event_id=eid,
                        type="message.created",
                        data={
                            "message_id": eid,
                            "kind": "card",
                            "content": "recommendation",
                            "payload": {"type": "recommendation", "picks": picks, "meta": meta},
                        },
                        actor_id="assistant",
                    )
                except Exception:
                    pass
            # Expose run context in followup_context
            try:
                run_id = r.get("run_id")
                symbols = r.get("symbols") or []
                # store context
                store.update_state(sid, {"active_run_id": run_id, "active_symbols": symbols})
                agent_trace.append({"step": "refresh_done", "status": "completed", "symbols": symbols})
            except Exception:
                pass
        else:
            # analyze_symbol / followup_tp / followup_why -> deterministic synthesis only
            # 1) Resolve symbol (no default-first)
            tgt = resolve_targets(sid, message)
            if tgt.get("kind") != "symbol":
                degraded = True
                degrade_reason = "symbol_unresolved"
                reply = "需要明确标的：可输入代码/名称；如基于推荐，支持‘第几只/这只’等指代。"
            else:
                resolved_symbol = str(tgt.get("symbol"))
                call("set_session_focus", {"session_id": sid, "symbol": resolved_symbol, "reason": str(tgt.get("reason") or "followup")})
                agent_trace.append({"step": "resolve_symbol", "status": "completed", "symbol": resolved_symbol, "reason": tgt.get("reason")})
                # 2) Gather tool context
                plan_steps: List[Tuple[str, Dict[str, Any]]] = []
                if name == "followup_why":
                    plan_steps.append(("explain_pick", {"symbol": resolved_symbol, "session_id": sid}))
                else:
                    plan_steps.extend([
                        ("get_ohlcv", {"symbol": resolved_symbol, "limit": 120}),
                        ("get_key_bands", {"symbol": resolved_symbol, "session_id": sid}),
                        ("get_strategy_context", {"symbol": resolved_symbol, "limit": 180}),
                    ])
                gathered: Dict[str, Any] = {}
                for (tool_name, args2) in plan_steps[:4]:
                    rr = call(tool_name, args2)
                    gathered[tool_name] = rr.data
                    agent_trace.append({"step": tool_name, "status": "ok" if rr.ok else "error"})
                # 3) Deterministic reply (no LLM)
                if name == "followup_why":
                    item = ((gathered.get("explain_pick") or {}) if isinstance(gathered.get("explain_pick"), dict) else {})
                    text = ((item.get("text") if isinstance(item.get("text"), str) else None) or "") if item else ""
                    reply = text or f"{resolved_symbol} 的推荐原因数据不足。"
                else:
                    bands = (((gathered.get("get_key_bands") or {}) if isinstance(gathered.get("get_key_bands"), dict) else {}).get("bands") or {})
                    strat = (gathered.get("get_strategy_context") or {}) if isinstance(gathered.get("get_strategy_context"), dict) else {}
                    lines = []
                    lines.append(f"标的：{resolved_symbol}")
                    if bands:
                        lines.append(f"关键带：S1={bands.get('S1')} S2={bands.get('S2')} R1={bands.get('R1')} R2={bands.get('R2')}")
                    if strat:
                        try:
                            lines.append(
                                f"指标：ATR%={float(strat.get('atr_pct', 0.0)):.2%} RSI2={float(strat.get('rsi2', 0.0)):.1f} "
                                f"Bias6={float(strat.get('bias6', 0.0)):.2%} 宽带={float(strat.get('bbwidth20', 0.0)):.2%}"
                            )
                        except Exception:
                            pass
                    lines.append("动作建议：\n- A窗口：结构明朗时试探，遵守止损\n- B窗口：上破确认后跟进，量能配合")
                    reply = "\n".join(lines)

    else:
        if intent["name"] == "general_chat":
            client = LLMClient()
            hist = store.load_history(sid, limit=20)
            messages = _llm_messages_for_general(hist)
            try:
                resp = client.chat(messages, temperature=0.3)
                reply = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception as e:  # noqa: BLE001
                degraded = True
                degrade_reason = f"llm_error:{e}"
                reply = "当前解释服务暂不可用，请尝试具体指令，例如：最新推荐 / 研究 600519 / 这三只都重新算。"

    # Save tool trace for debugging
    try:
        store.update_state(sid, {"last_tool_trace": tool_trace, "last_agent_trace": agent_trace})
    except Exception:
        pass

    assistant_mid = store.append_message(sid, "assistant", reply, require_event=True)
    return {
        "session_id": sid,
        "reply": reply,
        "tool_trace": tool_trace,
        "assistant_message_id": assistant_mid,
        "agent_trace": agent_trace,
        "resolved_symbol": resolved_symbol,
        "degraded": degraded,
        "degrade_reason": degrade_reason,
        "followup_context": {"active_run_id": store.get_state(sid).get("active_run_id"), "active_symbols": store.get_state(sid).get("active_symbols")},
    }
