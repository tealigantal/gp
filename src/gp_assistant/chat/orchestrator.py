from __future__ import annotations

"""
Chat Orchestrator (Tool-using Agent)

Routes intents to deterministic tools first, uses LLM to synthesize when helpful,
and degrades gracefully when LLM is unavailable.
Keeps compatibility with existing recommendation flow and event cards.
"""

from datetime import datetime
import os
from typing import Any, Dict, List, Optional, Tuple

from . import event_store
from . import session_store as store
from .agent_tools import build_registry
from .intent import detect_intent
from .intent_classifier import classify_intent_llm
from .intent_schema import IntentClassification
from .render import render_recommendation_narrative
from .slot_resolver import resolve_targets
from .finance_intents import assess_rr as _assess_rr, compare_symbols as _compare_symbols, ask_no_trade_reason as _ask_no_trade_reason, refresh_trade_plan as _refresh_trade_plan, exit_decision as _exit_decision
from ..llm.client import LLMClient
from ..recommend.compact_payload import compact_recommend_meta
from ..core.paths import store_dir
import json
from ..recommend.runner import run as recommend_run
from ..core.types import ToolResult
from ..recommend.artifact_store import build_v2_dict_from_v1, persist_artifact_v2
from ..kernel.facade import get_gated_artifact_v2
from ..kernel.facade import compare_symbols as kernel_compare_symbols, get_pick_detail as kernel_pick_detail
from .run_context import require_active_run_or_fail


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

    # LLM-first hybrid intent classification (guarded by env)
    def _truthy(v: str | None) -> bool:
        if v is None:
            return False
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}

    use_llm = _truthy(os.getenv("GP_ENABLE_LLM_INTENT", "0"))
    llm_ic: Optional[IntentClassification] = None
    final_intent_name: Optional[str] = None
    fallback_used = False

    if use_llm:
        try:
            llm_ic = classify_intent_llm(sid, message)
        except Exception:
            llm_ic = None

    # Confidence threshold (configurable)
    try:
        _thr = float(os.getenv("GP_INTENT_CONFIDENCE", "0.72"))
    except Exception:
        _thr = 0.72

    # Map LLM intent to internal intent names
    intent_map = {
        "recommend": "recommend",
        "ask_no_trade_reason": "ask_no_trade_reason",
        "ranking_explain": "ranking_explain",
        "compare_symbols": "compare_symbols",
        "analyze_symbol": "analyze_symbol",
        "exit_decision": "exit_decision",
        "refresh_recommend": "refresh_trade_plan",
        "general_explain": "general_explain",
        "unknown": "general_chat",
    }

    # Guard: downgrade general_explain when user actually asks trade actions
    def _looks_like_trade_action(text: str) -> bool:
        s = (text or "").lower()
        kws = ["买", "买入", "卖", "卖出", "要不要", "该不该", "能不能做", "能做吗", "上不", "空仓", "建议买", "建议卖", "减仓", "清仓"]
        return any(k in s for k in kws)

    if llm_ic and (llm_ic.intent != "unknown") and (llm_ic.confidence or 0.0) >= _thr:
        mapped = intent_map.get(llm_ic.intent or "unknown", "general_chat")
        # Guardrails: if LLM says general_explain but message includes trade action, fallback to rules
        if mapped == "general_explain" and _looks_like_trade_action(message):
            intent = detect_intent(message)
            final_intent_name = intent.get("name")
            fallback_used = True
        else:
            # adopt LLM intent
            intent = {"name": mapped, "slots": {}}
            final_intent_name = mapped
            # Prefer LLM slots: set focus / compare symbols for deterministic layer
            try:
                if llm_ic.symbol:
                    store.set_focus(sid, llm_ic.symbol, reason="llm_classifier")
                elif llm_ic.ordinal and llm_ic.ordinal >= 1:
                    stx = store.get_state(sid)
                    syms0 = list(stx.get("active_symbols") or [])
                    if syms0 and len(syms0) >= int(llm_ic.ordinal):
                        store.set_focus(sid, str(syms0[int(llm_ic.ordinal) - 1]), reason=f"llm_ordinal_{llm_ic.ordinal}")
                if mapped == "compare_symbols" and llm_ic.symbols:
                    store.set_compare_symbols(sid, [str(x) for x in llm_ic.symbols if str(x)])
                # topk slot passthrough if query_rewrite includes topk=N (optional)
            except Exception:
                pass
    else:
        # Fallback: use legacy rule-based detector
        intent = detect_intent(message)
        final_intent_name = intent.get("name")
        fallback_used = True
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
            # Override reply with clear Chinese message
            reply = "已生成推荐清单，请查看卡片。"
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

            # --- Upgrade: persist V2 artifact, set session context, and rewrite card payload to V2 run_id form ---
            try:
                v2 = build_v2_dict_from_v1(res if isinstance(res, dict) else {})
                run_id = str(v2.get("run_id") or v2.get("as_of") or "")
                if run_id:
                    try:
                        persist_artifact_v2(run_id, v2)
                    except Exception:
                        pass
                    try:
                        gated = get_gated_artifact_v2(run_id=run_id)
                    except Exception:
                        gated = v2
                    # symbols order from items
                    symbols: List[str] = []
                    try:
                        items = (gated.get("items") or []) if isinstance(gated, dict) else []
                        if isinstance(items, list) and items:
                            symbols = [str((it or {}).get("symbol") or "") for it in items if isinstance(it, dict)]
                        if not symbols:
                            symbols = list((gated.get("symbols") or []) if isinstance(gated, dict) else [])
                    except Exception:
                        symbols = []

                    # Update reply according to tradeable (avoid garbled text)
                    try:
                        if not bool((gated or {}).get("tradeable", True)):
                            reply = "当前建议空仓，请查看卡片中的原因。"
                        else:
                            reply = "已生成推荐清单，请查看卡片。"
                    except Exception:
                        pass
                    # session context
                    try:
                        store.update_state(sid, {"active_run_id": run_id, "active_symbols": symbols})
                    except Exception:
                        pass
                    # compose v2 card payload
                    top_syms = [s for s in symbols[:3] if s]
                    payload_v2 = {
                        "type": "recommendation",
                        "artifact_version": "v2",
                        "source": "gated_v2",
                        "run_id": run_id,
                        "as_of": v2.get("as_of"),
                        "summary": {
                            "total": len(symbols),
                            "top_symbols": top_syms,
                            "tradeable": bool((gated or {}).get("tradeable", False)),
                            "market_regime": (gated or {}).get("market_regime"),
                            "run_gating": (lambda rg: ({
                                "decision": rg.get("decision"),
                                "reasons": rg.get("reasons"),
                                "warnings": rg.get("warnings"),
                            } if isinstance(rg, dict) else None))((gated or {}).get("run_gating")),
                            "reason": (gated or {}).get("reason"),
                        },
                        "tool_trace_summary": {
                            "mode": ("service" if use_service else "default"),
                            "topk": int(intent["slots"].get("topk", 3)),
                            "persisted": True,
                        },
                    }
                    # rewrite message payload to v2 shape via message.edited event
                    try:
                        event_store.append_event(
                            sid,
                            event_id=f"edit-{eid}",
                            type="message.edited",
                            data={
                                "message_id": eid,
                                "payload": payload_v2,
                            },
                            actor_id="assistant",
                        )
                    except Exception:
                        pass
                    # adjust assistant reply to reflect no-trade if applicable
                    try:
                        if not bool((gated or {}).get("tradeable", True)):
                            reply = "当前建议空仓，请查看卡片中的原因。"
                    except Exception:
                        pass
            except Exception:
                # ignore v2 upgrade errors; keep v1 card
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

    elif intent["name"] in {"assess_rr", "compare_symbols", "ask_no_trade_reason", "ranking_explain", "refresh_trade_plan", "analyze_symbol", "followup_tp", "followup_why", "ask_nth", "exit_decision"}:
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
        # Strict ordinal handling: prefer active_symbols and short-circuit legacy flow
        if name == "ask_nth":
            try:
                n = int(intent["slots"].get("n", 1))
            except Exception:
                n = 1
            syms0 = list(store.get_state(sid).get("active_symbols") or [])
            if syms0 and len(syms0) >= n:
                resolved_symbol = str(syms0[n - 1])
                store.set_focus(sid, resolved_symbol, reason=f"ask_nth_{n}")
                agent_trace.append({"step": "resolve_symbol", "status": "completed", "symbol": resolved_symbol, "by": f"nth:{n}"})
                name = "analyze_symbol"
                intent = {"name": "analyze_symbol", "slots": {}}
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
            stx = store.get_state(sid)
            run_id = stx.get("active_run_id")
            focus = store.get_focus(sid)
            if not run_id or not focus:
                degraded = True
                reply = "请先生成推荐并指定标的"
            else:
                d0 = kernel_pick_detail(run_id, str(focus))
                if not d0.get("ok"):
                    degraded = True
                    reply = "数据不足，无法评估RR"
                else:
                    it0 = d0.get("item") or {}
                    rr0 = it0.get("reward_risk")
                    state0 = it0.get("execution_state")
                    act0 = bool(it0.get("actionable"))
                    reply = f"标的: {focus}\nRR={rr0} 状态={state0} {'(actionable)' if act0 else ''}"
        elif name == "compare_symbols":
            stx = store.get_state(sid)
            run_id = stx.get("active_run_id")
            syms = list(stx.get("active_symbols") or [])
            if not run_id or len(syms) < 2:
                degraded = True
                reply = "请先生成推荐（至少两只）"
            else:
                pair = syms[:2]
                out = kernel_compare_symbols(run_id, pair)
                items = out.get("items") or []
                def _score(it, k):
                    try:
                        return float((it or {}).get(k) or 0.0)
                    except Exception:
                        return 0.0
                if isinstance(items, list) and len(items) >= 2:
                    a, b = items[0], items[1]
                    explain = (
                        f"对比：{a.get('symbol')} vs {b.get('symbol')}\n"
                        f"- 综合分: { _score(a,'final_score'):.2f} vs { _score(b,'final_score'):.2f}\n"
                        f"- 执行分: { _score(a,'execution_score'):.2f} vs { _score(b,'execution_score'):.2f}\n"
                        f"- 方向分: { _score(a,'alpha_score'):.2f} vs { _score(b,'alpha_score'):.2f}\n"
                        f"- 可靠性: { _score(a,'reliability_score'):.2f} vs { _score(b,'reliability_score'):.2f}\n"
                        f"结论：{a.get('symbol')} 更优"
                    )
                    reply = explain
                else:
                    reply = f"比较结果: winner={out.get('winner_symbol')}"
        elif name == "ranking_explain":
            stx = store.get_state(sid)
            run_id = stx.get("active_run_id")
            syms = list(stx.get("active_symbols") or [])
            if not run_id or not syms:
                degraded = True
                reply = "请先生成推荐"
            else:
                art = get_gated_artifact_v2(run_id=run_id)
                items = [it for it in (art.get("items") or []) if isinstance(it, dict)]
                # rank by actionable+scores
                def _rank_key(it):
                    return (
                        1 if bool(it.get("actionable") is True) else 0,
                        float(it.get("final_score") or 0.0),
                        float(it.get("execution_score") or 0.0),
                        float(it.get("alpha_score") or 0.0),
                        float(it.get("reliability_score") or 0.0),
                    )
                ranked = sorted(items, key=_rank_key, reverse=True)
                # parse n
                msg = (message or "")
                n = 1
                if "第二" in msg or "第2" in msg:
                    n = 2
                # guard
                if len(ranked) < 1:
                    reply = "当前无候选。"
                else:
                    first = ranked[0]
                    tgt = ranked[n-1] if len(ranked) >= n else first
                    def _f(x):
                        try:
                            return float(x)
                        except Exception:
                            return None
                    lines = []
                    if n == 1:
                        lines.append("为什么第一只排第一：")
                    else:
                        lines.append(f"为什么第{n}只不是第一：")
                    lines.append(
                        f"- 综合分更高：{(first.get('final_score'))} vs {(tgt.get('final_score'))}"
                    )
                    lines.append(
                        f"- 执行/形态更优：{(first.get('execution_state') or '-')}, 执行分={first.get('execution_score')}"
                    )
                    # gating
                    fg = (first.get('gating_decision') or {}).get('decision')
                    tg = (tgt.get('gating_decision') or {}).get('decision') if tgt else None
                    if fg or tg:
                        lines.append(f"- 门控：第一只={fg or '-'} 对比={tg or '-'}")
                    # rr/invalidation
                    rr1 = first.get('reward_risk'); rr2 = tgt.get('reward_risk') if tgt else None
                    if rr1 is not None or rr2 is not None:
                        lines.append(f"- RR：{rr1} vs {rr2}")
                    inv1 = first.get('invalidation'); inv2 = tgt.get('invalidation') if tgt else None
                    if inv1 or inv2:
                        lines.append(f"- 失效条件：{inv1 or []} vs {inv2 or []}")
                    reply = "\n".join(lines)
        elif name == "ask_no_trade_reason":
            stx = store.get_state(sid)
            run_id = stx.get("active_run_id")
            if not run_id:
                degraded = True
                reply = "请先生成推荐"
            else:
                art0 = get_gated_artifact_v2(run_id=run_id)
                if bool(art0.get("tradeable")):
                    reply = "当前可交易，并非空仓。"
                else:
                    reason = art0.get("reason")
                    rg = art0.get("run_gating") or {}
                    decision = rg.get("decision")
                    reasons = rg.get("reasons") or []
                    warnings = rg.get("warnings") or []
                    allow_n = sum(1 for it in (art0.get("items") or []) if (it.get('gating_decision') or {}).get('decision') == 'allow')
                    degraded_n = sum(1 for it in (art0.get("items") or []) if (it.get('gating_decision') or {}).get('decision') == 'degraded')
                    blocked_n = sum(1 for it in (art0.get("items") or []) if (it.get('gating_decision') or {}).get('decision') == 'blocked')
                    parts = []
                    if isinstance(reason, str) and reason:
                        parts.append(f"原因：{reason}")
                    if decision:
                        parts.append(f"运行门控：{decision}（{', '.join(reasons)}）")
                        if warnings:
                            parts.append(f"预警：{', '.join(warnings[:3])}")
                    parts.append(f"候选状态：allow={allow_n} degraded={degraded_n} blocked={blocked_n}")
                    if decision == 'allow' and not bool(art0.get('tradeable')):
                        parts.append("运行层未封禁，但当前候选整体不可执行/候选为空，因此今天仍建议空仓。")
                    reply = "\n".join(parts)
        elif name == "refresh_trade_plan":
            # Recompute via engine -> new v2 run
            res_v1b = recommend_run(topk=int(intent.get("slots", {}).get("topk", 3) or 3))
            v2b = build_v2_dict_from_v1(res_v1b)
            run_id2 = str(v2b.get("run_id"))
            try:
                persist_artifact_v2(run_id2, v2b)
            except Exception:
                pass
            gated2 = get_gated_artifact_v2(run_id=run_id2)
            symbols2 = [str((it or {}).get("symbol") or "") for it in (gated2.get("items") or []) if isinstance(it, dict)]
            store.update_state(sid, {"active_run_id": run_id2, "active_symbols": symbols2})
            agent_trace.append({"step": "refresh_done", "status": "completed", "symbols": symbols2})
            # Append new v2 recommendation card
            try:
                eid2 = f"card-reco-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
                payload2 = {
                    "type": "recommendation",
                    "artifact_version": "v2",
                    "source": "gated_v2",
                    "run_id": run_id2,
                    "as_of": v2b.get("as_of"),
                    "summary": {
                        "total": len(symbols2),
                        "top_symbols": symbols2[:3],
                        "tradeable": bool(gated2.get("tradeable", False)),
                        "market_regime": gated2.get("market_regime"),
                        "run_gating": gated2.get("run_gating"),
                        "reason": gated2.get("reason"),
                    },
                }
                event_store.append_event(
                    sid,
                    event_id=eid2,
                    type="message.created",
                    data={"message_id": eid2, "kind": "card", "content": "recommendation", "payload": payload2},
                    actor_id="assistant",
                )
            except Exception:
                pass
            reply = "已重新计算，请查看新推荐卡片。"
        elif name == "exit_decision":
            # SELL decision chain
            out = _exit_decision(sid, message)
            if not out.get("ok"):
                degraded = True
                reply = str(out.get("message") or "需要明确标的")
            else:
                decision = str(out.get("decision") or "WATCH").upper()
                rs = ", ".join([str(x) for x in (out.get("reasons") or [])])
                reply = f"建议：{decision}\n依据：{rs or '综合结构与风控'}"
        else:
            # analyze_symbol / followup_tp / followup_why -> deterministic synthesis only
            # 1) Resolve symbol (no default-first)
            tgt = resolve_targets(sid, message)
            if tgt.get("kind") != "symbol":
                degraded = True
                degrade_reason = "symbol_unresolved"
                # If user asked for sell/hold type in exit decision path we handle earlier; here generic followups
                reply = "需要明确标的：可输入代码/名称；如基于推荐，支持‘第几只/这只’等指代。"
            else:
                resolved_symbol = str(tgt.get("symbol"))
                call("set_session_focus", {"session_id": sid, "symbol": resolved_symbol, "reason": str(tgt.get("reason") or "followup")})
                agent_trace.append({"step": "resolve_symbol", "status": "completed", "symbol": resolved_symbol, "reason": tgt.get("reason")})
                # 2) Prefer canonical artifact pick detail when in current run
                stx = store.get_state(sid)
                run_id = stx.get("active_run_id")
                syms = list(stx.get("active_symbols") or [])
                used_pick = False
                if run_id and resolved_symbol in syms:
                    d0 = kernel_pick_detail(run_id, resolved_symbol)
                    if d0.get("ok"):
                        it0 = d0.get("item") or {}
                        used_pick = True
                        if name == "followup_why":
                            # structured explanation
                            parts = []
                            parts.append(f"标的：{resolved_symbol}")
                            parts.append(f"执行：{it0.get('execution_state')} {'(可执行)' if it0.get('actionable') else ''}")
                            parts.append(f"分数：final={it0.get('final_score')} α={it0.get('alpha_score')} 执行={it0.get('execution_score')} 可靠={it0.get('reliability_score')}")
                            gd = it0.get('gating_decision') or {}
                            if gd:
                                parts.append(f"门控：{gd.get('decision')} {', '.join((gd.get('reasons') or [])[:3])}")
                            rr = it0.get('reward_risk')
                            inv = it0.get('invalidation')
                            if rr is not None:
                                parts.append(f"RR：{rr}")
                            if inv:
                                parts.append(f"失效：{', '.join([str(x) for x in inv])}")
                            reply = "\n".join(parts)
                        else:
                            # analyze/tp summary using pick detail
                            parts = []
                            parts.append(f"标的：{resolved_symbol}")
                            ez = it0.get('entry_zone')
                            stop = it0.get('stop'); take = it0.get('take_profit')
                            if isinstance(ez, list) and len(ez) >= 2:
                                parts.append(f"买点：{ez[0]} ~ {ez[1]}")
                            if stop is not None:
                                parts.append(f"止损：{stop}")
                            if isinstance(take, list) and take:
                                parts.append(f"止盈：{', '.join([str(x) for x in take])}")
                            parts.append(f"状态：{it0.get('execution_state')} {'(可执行)' if it0.get('actionable') else ''}")
                            reply = "\n".join(parts)
                if not used_pick:
                    # Fallback to tools pipeline
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
        if intent["name"] in {"general_chat", "general_explain"}:
            client = LLMClient()
            hist = store.load_history(sid, limit=20)
            # safer general explain prompt (no trading actions)
            sys_prompt = (
                "你是交易研究助理的解释通道。\n"
                "- 禁止输出任何新的买入/卖出/加减仓/止损/止盈/空仓建议。\n"
                "- 仅可解释术语、流程、指标含义、评分含义、门控(gating)等。\n"
                "- 如果用户在问交易动作（如 买/卖/上/能不能做），请提醒‘请使用推荐/分析/退出等确定性指令’，不要给建议。\n"
            )
            messages = ([{"role": "system", "content": sys_prompt}] + [{"role": h["role"], "content": h["content"]} for h in hist[-6:]])
            try:
                resp = client.chat(messages, temperature=0.2)
                reply = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                # guard: strip potential imperatives
                if _looks_like_trade_action(message):
                    reply = "该问题涉及交易动作，请使用：最新推荐 / 研究 [代码] / 要不要减仓 / 为什么今天不做 等确定性指令。"
            except Exception as e:  # noqa: BLE001
                degraded = True
                degrade_reason = f"llm_error:{e}"
                reply = "当前解释服务暂不可用，请尝试具体指令，例如：最新推荐 / 研究 600519 / 这三只都重新算。"

    # Save tool trace for debugging
    # Append minimal intent debug meta for observability
    try:
        intent_debug = {
            "original_message": message,
            "llm_intent": (llm_ic.intent if llm_ic else None),
            "llm_confidence": (llm_ic.confidence if llm_ic else None),
            "llm_slots": (
                {
                    "symbol": getattr(llm_ic, "symbol", None),
                    "symbols": getattr(llm_ic, "symbols", None),
                    "ordinal": getattr(llm_ic, "ordinal", None),
                    "query_rewrite": getattr(llm_ic, "query_rewrite", None),
                }
                if llm_ic
                else None
            ),
            "fallback_used": bool(fallback_used),
            "final_intent": final_intent_name,
            "final_symbol": resolved_symbol,
            "final_ordinal": (getattr(llm_ic, "ordinal", None) if llm_ic else None),
            "active_run_id": store.get_state(sid).get("active_run_id"),
        }
        tool_trace["intent_debug"] = intent_debug
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
