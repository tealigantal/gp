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
        # Default to DeepSeek-friendly model name if not provided
        self.model = (model or cfg.chat_model or "deepseek-chat").strip()
        # timeout<=0 表示不限制，由 requests 使用阻塞式无超时
        self.timeout = cfg.request_timeout_sec

    @staticmethod
    def build_payload(
        model: str,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        stream: bool = False,
        response_format: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": float(temperature),
            "stream": bool(stream),
        }
        if response_format:
            payload["response_format"] = response_format
        if extra:
            for k, v in extra.items():
                if k not in payload and v is not None:
                    payload[k] = v
        return payload

    def available(self) -> Tuple[bool, str]:
        if not self.base_url:
            return False, "LLM_BASE_URL 未配置"
        if not self.api_key:
            return False, "LLM_API_KEY 未配置"
        return True, "ok"

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        stream: bool = False,
        json_mode: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(f"LLM 未就绪：{reason}")

        url = self.base_url.rstrip("/") + "/chat/completions"
        response_format = {"type": "json_object"} if json_mode else None
        payload = self.build_payload(
            self.model,
            messages,
            temperature=temperature,
            stream=stream,
            response_format=response_format,
            extra=extra,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        timeout = None if (isinstance(self.timeout, (int, float)) and self.timeout <= 0) else self.timeout
        resp = requests.post(url, headers=headers, data=data, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def run_chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        *,
        temperature: float = 0.2,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Single chat/completions step with optional tools exposure.

        Returns a dict like { role: 'assistant', content: str|None, tool_calls: [ ... ]|None }
        """
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(f"LLM 未就绪：{reason}")

        url = self.base_url.rstrip("/") + "/chat/completions"
        payload: Dict[str, Any] = {
            "model": (model or self.model or "deepseek-chat"),
            "messages": messages,
            "temperature": float(temperature),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        timeout = None if (isinstance(self.timeout, (int, float)) and self.timeout <= 0) else self.timeout
        resp = requests.post(url, headers=headers, data=data, timeout=timeout)
        resp.raise_for_status()
        obj = resp.json()
        ch = ((obj or {}).get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        # Normalize minimal surface
        out = {
            "role": msg.get("role") or "assistant",
            "content": msg.get("content"),
            "tool_calls": msg.get("tool_calls") or [],
        }
        return out
