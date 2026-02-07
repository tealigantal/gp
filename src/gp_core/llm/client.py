from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml
import requests


@dataclass
class LLMConfig:
    provider: str
    base_url: str
    model: str
    api_key_env: str
    temperature: float
    max_tokens: int
    timeout_sec: int
    retries: int
    json_mode: bool


def load_llm_config(path: str) -> LLMConfig:
    raw = yaml.safe_load(open(path, 'r', encoding='utf-8').read()) or {}
    # Fail fast if provider is mock or missing
    prov = str(raw.get('provider', '')).lower()
    if not prov or prov == 'mock':
        raise RuntimeError('LLM provider invalid; set configs/llm.yaml with a real provider and API key env')
    return LLMConfig(
        provider=prov,
        base_url=str(raw.get('base_url', '') or ''),
        model=str(raw.get('model', '')),
        api_key_env=str(raw.get('api_key_env', '')),
        temperature=float(raw.get('temperature', 0.2)),
        max_tokens=int(raw.get('max_tokens', 1500)),
        timeout_sec=int(raw.get('timeout_sec', 60)),
        retries=int(raw.get('retries', 1)),
        json_mode=bool(raw.get('json_mode', True)),
    )


class LLMClient:
    def __init__(self, cfg_path: str):
        self.cfg = load_llm_config(cfg_path)
        api_key = os.getenv(self.cfg.api_key_env)
        if not api_key:
            raise RuntimeError(f'LLM API Key missing in env: {self.cfg.api_key_env}')
        self.api_key = api_key

    def chat(self, messages: List[Dict[str, Any]], *, json_response: bool = True) -> Dict[str, Any]:
        url = self.cfg.base_url.rstrip('/') + '/chat/completions'
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json; charset=utf-8',
            'Accept': 'application/json',
        }
        payload: Dict[str, Any] = {
            'model': self.cfg.model,
            'messages': messages,
            'temperature': self.cfg.temperature,
            'max_tokens': self.cfg.max_tokens,
        }
        if json_response or self.cfg.json_mode:
            payload['response_format'] = {"type": "json_object"}
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        last_exc: Optional[Exception] = None
        for _ in range(self.cfg.retries + 1):
            try:
                resp = requests.post(url, headers=headers, data=data, timeout=self.cfg.timeout_sec)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
        assert last_exc is not None
        raise last_exc

