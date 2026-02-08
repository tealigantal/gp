from __future__ import annotations

from gp_assistant.llm.client import LLMClient


def test_build_payload_shape():
    payload = LLMClient.build_payload("gpt-4o-mini", [{"role": "user", "content": "hi"}], temperature=0.3, stream=False)
    assert set(payload.keys()) == {"model", "messages", "temperature", "stream"}
    assert payload["model"]
    assert isinstance(payload["messages"], list)
    assert payload["temperature"] == 0.3
    assert payload["stream"] is False

