# 简介：LLM 客户端（OpenAI Chat Completions 兼容）。从环境读取配置；
# 未配置时优雅降级为可读提示，避免阻断对话路径。
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple
import requests

from ..core.config import load_config


class LLMClient:
    """OpenAI Chat Completions compatible client with graceful degradation.

    - Reads base URL, API key, model from env (via AppConfig)
    - If API key or base URL missing, returns a readable degraded reply.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        cfg = load_config()
        self.base_url = (base_url or cfg.llm_base_url or "").strip()
        self.api_key = (api_key or cfg.llm_api_key or "").strip()
        self.model = (model or cfg.chat_model or "gpt-4o-mini").strip()
        self.timeout = cfg.request_timeout_sec

    @staticmethod
    def build_payload(model: str, messages: List[Dict[str, Any]], temperature: float = 0.2, stream: bool = False) -> Dict[str, Any]:
        return {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "stream": bool(stream),
        }

    def available(self) -> Tuple[bool, str]:
        if not self.base_url:
            return False, "LLM_BASE_URL 未配置"
        if not self.api_key:
            return False, "LLM_API_KEY 未配置"
        return True, "ok"

    def chat(self, messages: List[Dict[str, Any]], temperature: float = 0.2, stream: bool = False) -> Dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            # graceful degradation
            content = f"【降级】LLM未配置：{reason}。原样回显：" + (messages[-1].get("content", "") if messages else "")
            return {"choices": [{"message": {"role": "assistant", "content": content}}]}

        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = self.build_payload(self.model, messages, temperature=temperature, stream=stream)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        resp = requests.post(url, headers=headers, data=data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
