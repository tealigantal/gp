# 简介：对话编排器。基于意图识别在 LLM 闲聊与策略荐股之间路由，
# 维护会话上下文与最近一次推荐，支持“为什么/买卖点”等追问。
from __future__ import annotations

from typing import Any, Dict, Optional

from .intent import detect_intent
from .render import render_recommendation
from ..guards.output_guard import guard
from ..llm.client import LLMClient
from ..recommend import agent as rec_agent
from . import session_store as store


def handle_message(session_id: Optional[str], message: str) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    store.append_message(sid, "user", message)
    intent = detect_intent(message)
    tool_trace = {"triggered_recommend": False, "recommend_result": None}
    reply = ""
    if intent["name"] == "recommend":
        res = rec_agent.run(topk=intent["slots"].get("topk", 3))
        store.save_last_recommend(sid, res)
        txt = render_recommendation(res)
        ok, safe_txt = guard(txt)
        reply = safe_txt if ok else safe_txt
        tool_trace = {"triggered_recommend": True, "recommend_result": res}
    else:
        # normal chat via LLM with graceful degradation
        client = LLMClient()
        hist = store.load_history(sid, limit=20)
        messages = ([{"role": "system", "content": "你是交易研究助理。"}] +
                    [{"role": h["role"], "content": h["content"]} for h in hist[-6:]] +
                    [{"role": "user", "content": message}])
        resp = client.chat(messages, temperature=0.3)
        reply = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        # If user asked why/trade points and we have last recommend, append deterministic explanation
        if intent["name"] in {"followup_why", "followup_tp"}:
            last = store.load_last_recommend(sid)
            if last:
                extra = render_recommendation(last)
                ok, safe_extra = guard(extra)
                reply += "\n\n【基于上次推荐的结构化说明】\n" + (safe_extra)
    store.append_message(sid, "assistant", reply)
    return {"session_id": sid, "reply": reply, "tool_trace": tool_trace}
