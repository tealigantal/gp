from __future__ import annotations

from pathlib import Path

from src.gp_assistant.config import AssistantConfig
from src.gp_assistant.agent import ChatAgent


class StubLLM:
    def __init__(self, capture):
        self.capture = capture
    def chat(self, messages, json_response=False):
        # assert no prefixes leaked
        joined = str(messages)
        assert 'user>' not in joined
        assert 'agent>' not in joined
        assert 'tool>' not in joined
        self.capture.append(messages)
        return {'choices':[{'message':{'content':'ok'}}]}


def test_prompt_prefix_not_in_llm_context(tmp_path: Path, monkeypatch):
    # Minimal assistant config
    (tmp_path / 'configs').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'configs' / 'assistant.yaml').write_text('workspace_root: .\n', encoding='utf-8')
    cfg = AssistantConfig.load(str(tmp_path / 'configs' / 'assistant.yaml'))
    agent = ChatAgent(cfg)
    cap = []
    agent.llm = StubLLM(cap)  # type: ignore
    out = agent._chat_once('测试一下上下文')
    assert 'ok' in out

