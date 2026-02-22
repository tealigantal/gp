# src/gp_assistant/chat/orchestrator.py
"""
对话编排器：
- 意图识别：recommend / followup_why / followup_tp / chat
- recommend：调用 recommend.runner（自动支持 dev/default/未来模式）
- chat：调用 LLM（不可用时优雅降级）
- 事件流：把“推荐卡片”写入 event_store，便于前端稳定渲染/回放
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from . import event_store
from . import session_store as store
from .intent import detect_intent
from .render import render_recommendation_narrative
from ..llm.client import LLMClient
from ..recommend.runner import run as recommend_run


def handle_message(session_id: Optional[str], message: str, message_id: Optional[str] = None) -> Dict[str, Any]:
    sid = store.ensure_session(session_id)
    store.append_message(sid, "user", message, message_id=message_id)

    intent = detect_intent(message)
    tool_trace: Dict[str, Any] = {"triggered_recommend": False, "recommend_result": None}
    reply = ""

    if intent["name"] == "recommend":
        try:
            res = recommend_run(topk=int(intent["slots"].get("topk", 3)))
            store.save_last_recommend(sid, res)

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

        messages = (
            [{"role": "system", "content": "你是交易研究助理。"}]
            + [{"role": h["role"], "content": h["content"]} for h in hist[-6:]]
            + [{"role": "user", "content": message}]
        )

        # 强化 chat 模式系统提示，避免免责声明/拒答
        sys_prompt_chat = (
            "你是交易研究助理。"
            "严禁输出任何‘无法提供投资建议/个股推荐/不构成投资建议/仅供参考/建议咨询专业人士’等拒答或免责声明句式；"
            "涉及选股/建议/买卖点/持仓等问题时，直接给出具体看法与观察要点，不要写合规前言。"
        )
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
                reply += "\n\n〖基于上次推荐的说明〗\n" + extra

    assistant_mid = store.append_message(sid, "assistant", reply, require_event=True)
    return {"session_id": sid, "reply": reply, "tool_trace": tool_trace, "assistant_message_id": assistant_mid}