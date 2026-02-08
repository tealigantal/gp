from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests
import re
import yaml


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
    return LLMConfig(
        provider=raw.get('provider', 'openai'),
        base_url=str(raw.get('base_url', 'https://api.openai.com/v1')),
        model=str(raw.get('model', 'gpt-4o-mini')),
        api_key_env=str(raw.get('api_key_env', 'OPENAI_API_KEY')),
        temperature=float(raw.get('temperature', 0.0)),
        max_tokens=int(raw.get('max_tokens', 1200)),
        timeout_sec=int(raw.get('timeout_sec', 60)),
        retries=int(raw.get('retries', 1)),
        json_mode=bool(raw.get('json_mode', False)),
    )


class SimpleLLMClient:
    def __init__(self, cfg_path: str, overrides: Optional[Dict[str, Any]] = None):
        self.cfg = load_llm_config(cfg_path)
        if overrides:
            if 'temperature' in overrides and overrides['temperature'] is not None:
                self.cfg.temperature = float(overrides['temperature'])
            if 'max_tokens' in overrides and overrides['max_tokens'] is not None:
                self.cfg.max_tokens = int(overrides['max_tokens'])
            if 'timeout' in overrides and overrides['timeout'] is not None:
                self.cfg.timeout_sec = int(overrides['timeout'])
        if self.cfg.provider.lower() == 'mock':
            self.api_key = 'mock'
            return
        api_key = os.getenv(self.cfg.api_key_env)
        if not api_key:
            raise RuntimeError(f"LLM API Key missing in env: {self.cfg.api_key_env}")
        self.api_key = api_key

    # --- Surrogate-safe sanitization ---
    _SURROGATE_RE = re.compile(r"[\ud800-\udfff]")

    @classmethod
    def strip_surrogates(cls, s: str) -> str:
        return cls._SURROGATE_RE.sub("", s)

    @classmethod
    def sanitize_for_llm(cls, obj):  # noqa: ANN001
        if obj is None:
            return None
        if isinstance(obj, str):
            return cls.strip_surrogates(obj)
        if isinstance(obj, list):
            return [cls.sanitize_for_llm(x) for x in obj]
        if isinstance(obj, dict):
            return {k: cls.sanitize_for_llm(v) for k, v in obj.items()}
        return obj

    @staticmethod
    def find_surrogates(s: str, max_hits: int = 10):
        hits = []
        for i, ch in enumerate(s):
            o = ord(ch)
            if 0xD800 <= o <= 0xDFFF:
                hits.append((i, hex(o)))
                if len(hits) >= max_hits:
                    break
        return hits

    def chat(self, messages: List[Dict[str, Any]], json_response: bool = False) -> Dict[str, Any]:
        if self.cfg.provider.lower() == 'mock':
            content = json.dumps({'echo': True, 'messages': [m.get('role') for m in messages]}, ensure_ascii=False)
            return {'choices': [{'message': {'content': content}}]}
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
        payload = self.sanitize_for_llm(payload)
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        last_exc: Optional[Exception] = None
        for i in range(self.cfg.retries + 1):
            try:
                resp = requests.post(url, headers=headers, data=data, timeout=self.cfg.timeout_sec)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
        assert last_exc is not None
        raise last_exc
