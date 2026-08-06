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


def test_strict_tools_use_beta_endpoint_and_normal_chat_uses_base_endpoint(monkeypatch):
    urls = []

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    def post(url, **_kwargs):
        urls.append(url)
        return Response()

    monkeypatch.setattr("gp_assistant.llm.client.requests.post", post)
    client = LLMClient(base_url="https://api.deepseek.com", api_key="test", model="deepseek-v4-flash")
    client.chat([{"role": "user", "content": "你好"}])
    client.run_chat_with_tools(
        [{"role": "user", "content": "你好"}],
        tools=[LLMClient.strict_tool(name="route", description="route", parameters={})],
    )

    assert urls == [
        "https://api.deepseek.com/chat/completions",
        "https://api.deepseek.com/beta/chat/completions",
    ]
