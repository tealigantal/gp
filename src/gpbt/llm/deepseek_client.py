from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import List, Optional

import requests


@dataclass
class LLMConfig:
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    api_key_env: str = "DEEPSEEK_API_KEY"
    temperature: float = 0.0
    max_tokens: int = 1200
    timeout_sec: int = 60
    retries: int = 2
    json_mode: bool = True  # force DeepSeek JSON mode


class DeepseekClient:
    def __init__(self, cfg: Optional[LLMConfig] = None):
        self.cfg = cfg or LLMConfig()
        key = os.getenv(self.cfg.api_key_env)
        if not key:
            raise RuntimeError(f"LLM API Key missing in env: {self.cfg.api_key_env}")
        self.api_key = key

    def chat(self, messages: List[dict]) -> dict:
        if not self.cfg.json_mode:
            raise RuntimeError("LLM JSON mode is required (configs/llm.yaml json_mode must be true)")
        url = self.cfg.base_url.rstrip('/') + '/chat/completions'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
        }
        payload = {
            'model': self.cfg.model,
            'messages': messages,
            'temperature': self.cfg.temperature,
            'max_tokens': max(1600, self.cfg.max_tokens),
            'response_format': {"type": "json_object"},
        }
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        last_exc = None
        for i in range(self.cfg.retries + 1):
            try:
                resp = requests.post(url, headers=headers, data=data, timeout=self.cfg.timeout_sec)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                if i == self.cfg.retries:
                    raise
                time.sleep(2 ** i)
        raise last_exc  # type: ignore
