from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..core.config import load_config


class LLMClient:
    """OpenAI Chat Completions compatible client."""

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        cfg = load_config()
        self.base_url = (base_url or cfg.llm_base_url or "").strip()
        self.api_key = (api_key or cfg.llm_api_key or "").strip()
        self.model = (model or cfg.chat_model or "deepseek-v4-flash").strip()
        self.agent_model = (getattr(cfg, "agent_model", None) or self.model).strip()
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
            for key, value in extra.items():
                if key not in payload and value is not None:
                    payload[key] = value
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

    @staticmethod
    def strict_tool(
        *,
        name: str,
        description: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        schema = dict(parameters or {})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("additionalProperties", False)
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": schema,
                "strict": True,
            },
        }

    def run_chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
        *,
        temperature: float = 0.2,
        model: Optional[str] = None,
        tool_choice: Optional[Any] = None,
        thinking: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(f"LLM 未就绪：{reason}")

        url = self.base_url.rstrip("/") + "/chat/completions"
        payload: Dict[str, Any] = {
            "model": model or self.model or "deepseek-v4-flash",
            "messages": messages,
            "temperature": float(temperature),
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
        if thinking is not None:
            payload["thinking"] = thinking
        if extra:
            for key, value in extra.items():
                if key not in payload and value is not None:
                    payload[key] = value
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
        choice = ((obj or {}).get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        return {
            "role": msg.get("role") or "assistant",
            "content": msg.get("content"),
            "tool_calls": msg.get("tool_calls") or [],
            "reasoning_content": msg.get("reasoning_content"),
        }

    def agent_tool_step(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        *,
        tool_choice: Optional[Any] = "required",
        temperature: float = 0.0,
        thinking: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.run_chat_with_tools(
            messages,
            tools=tools,
            temperature=temperature,
            model=self.agent_model,
            tool_choice=tool_choice,
            thinking=thinking,
        )
