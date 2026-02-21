# 简介：对话编排器。基于意图识别在 LLM 闲聊与策略荐股之间路由，
# 维护会话上下文与最近一次推荐，支持“为什么/买卖点”等追问。
from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime

from .intent import detect_intent
from .render import render_recommendation, render_recommendation_narrative
from ..llm.client import LLMClient
from ..recommend import agent as rec_agent
from . import session_store as store
from . import event_store


def handle_message(session_id: Optional[str], message: str) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    store.append_message(sid, "user", message)
    intent = detect_intent(message)
    tool_trace = {"triggered_recommend": False, "recommend_result": None}
    reply = ""
    if intent["name"] == "recommend":
        try:
            res = rec_agent.run(topk=intent["slots"].get("topk", 3))
            store.save_last_recommend(sid, res)
            # Prefer LLM narrative; 若不可用，仅提示缺失，不回退规则清单
            reply = render_recommendation_narrative(res)
            tool_trace = {"triggered_recommend": True, "recommend_result": res}
            # 同步追加一条“推荐卡片”到事件流，便于前端稳定渲染/回放
            try:
                picks = res.get("picks") if isinstance(res, dict) else None
                if isinstance(picks, list) and picks:
                    eid = f"card-reco-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
                    event_store.append_event(
                        sid,
                        event_id=eid,
                        type="message.created",
                        data={
                            "message_id": eid,
                            "kind": "card",
                            "content": "recommendation",
                            "payload": {"type": "recommendation", "picks": picks},
                        },
                        actor_id="assistant",
                    )
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            reply = f"[data_unavailable] 推荐生成失败：{e}"
            tool_trace = {"triggered_recommend": False, "error": str(e)}
    else:
        # normal chat via LLM with graceful degradation
        client = LLMClient()
        hist = store.load_history(sid, limit=20)
        messages = ([{"role": "system", "content": "你是交易研究助理。"}] +
                    [{"role": h["role"], "content": h["content"]} for h in hist[-6:]] +
                    [{"role": "user", "content": message}])
        # 强化 chat 模式系统提示，避免免责声明/拒答
        sys_prompt_chat = ("你是交易研究助理。"
                           "严禁输出任何‘无法提供投资建议/个股推荐/不构成投资建议/仅供参考/建议咨询专业人士’等拒答或免责声明句式；"
                           "涉及选股/建议/买卖点/持仓等问题时，直接给出具体看法与观察要点，不要写合规前言。")
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = sys_prompt_chat
        try:
            resp = client.chat(messages, temperature=0.3)
            reply = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:  # noqa: BLE001
            reply = f"[chat_unavailable] LLM 错误：{e}"
        # If user asked why/trade points and we have last recommend, append deterministic explanation
        if intent["name"] in {"followup_why", "followup_tp"}:
            last = store.load_last_recommend(sid)
            if last:
                extra = render_recommendation_narrative(last)
                reply += "\n\n【基于上次推荐的说明】\n" + extra
    store.append_message(sid, "assistant", reply)
    return {"session_id": sid, "reply": reply, "tool_trace": tool_trace}
