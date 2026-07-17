from __future__ import annotations

from gp_assistant.llm.client import LLMClient


def test_agent_tool_step_disables_thinking_for_required_tool_choice(monkeypatch):
    seen = {}

    def _run(self, messages, tools=None, **kwargs):
        seen.update(kwargs)
        return {"role": "assistant", "content": None, "tool_calls": []}

    monkeypatch.setattr(LLMClient, "run_chat_with_tools", _run)

    LLMClient(base_url="https://api.deepseek.com/beta", api_key="test", model="deepseek-v4-flash").agent_tool_step(
        [{"role": "user", "content": "你好"}],
        [],
    )

    assert seen["tool_choice"] == "required"
    assert seen["thinking"] == {"type": "disabled"}
