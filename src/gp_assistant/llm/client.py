from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, local
from time import monotonic
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import requests

from ..core.config import load_config
from ..core.paths import store_dir
from ..runtime.context_budget import (
    ROUTING_PAYLOAD_LIMIT_BYTES,
    encode_llm_payload,
)


_STATUS_LOCK = Lock()
_TRACE_LOCAL = local()
_PRODUCT_VERIFICATION_MAX_AGE_SEC = 1800.0
_RUNTIME_STATUS: Dict[str, Any] = {
    "last_call_success": None,
    "last_success_at": None,
    "last_error_at": None,
    "last_error": None,
    "last_http_status": None,
    "last_latency_ms": None,
    "last_response_model": None,
    "last_response_id": None,
    "product_chat_last_success": None,
    "product_chat_last_success_at": None,
    "product_chat_last_error_at": None,
    "product_chat_last_error": None,
    "product_chat_last_stage": None,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_status_path() -> Path:
    return store_dir() / "llm_runtime_status.json"


def _read_persisted_runtime_status() -> Dict[str, Any]:
    try:
        value = json.loads(_runtime_status_path().read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _write_persisted_runtime_status(status: Dict[str, Any]) -> None:
    path = _runtime_status_path()
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(status, ensure_ascii=False, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError:
        # Health telemetry must not make a completed chat turn fail.
        pass
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _update_runtime_status(update: Dict[str, Any]) -> None:
    """Keep LLM health visible across the two Uvicorn worker processes."""
    with _STATUS_LOCK:
        merged = {**_RUNTIME_STATUS, **_read_persisted_runtime_status(), **update}
        _RUNTIME_STATUS.update(merged)
        _write_persisted_runtime_status(merged)


def _record_call(
    *,
    success: bool,
    started_at: float,
    http_status: int | None = None,
    response: Dict[str, Any] | None = None,
    error: BaseException | None = None,
    stage: str = "llm_chat",
    request_model: str | None = None,
) -> None:
    now = _utc_now()
    update: Dict[str, Any] = {
        "last_call_success": bool(success),
        "last_http_status": http_status,
        "last_latency_ms": round((monotonic() - started_at) * 1000.0, 1),
    }
    if success:
        update.update(
            {
                "last_success_at": now,
                "last_error": None,
                "last_response_model": str((response or {}).get("model") or "") or None,
                "last_response_id": str((response or {}).get("id") or "") or None,
            }
        )
    else:
        update.update(
            {
                "last_error_at": now,
                "last_error": f"{type(error).__name__}:{error}" if error is not None else "unknown",
            }
        )
    _update_runtime_status(update)
    trace = {
        "stage": str(stage),
        "success": bool(success),
        "http_status": http_status,
        "latency_ms": update["last_latency_ms"],
        "request_model": request_model,
        "response_model": str((response or {}).get("model") or "") or None,
        "response_id": str((response or {}).get("id") or "") or None,
        "error_type": type(error).__name__ if error is not None else None,
    }
    calls = list(getattr(_TRACE_LOCAL, "calls", []))
    calls.append(trace)
    _TRACE_LOCAL.calls = calls


def reset_llm_call_trace() -> None:
    _TRACE_LOCAL.calls = []


def current_llm_call_trace() -> List[Dict[str, Any]]:
    return [dict(item) for item in list(getattr(_TRACE_LOCAL, "calls", []))]


def validate_product_llm_trace(trace: List[Dict[str, Any]]) -> None:
    def valid(item: Dict[str, Any]) -> bool:
        status = item.get("http_status")
        return bool(
            item.get("success") is True
            and isinstance(status, int)
            and 200 <= status < 300
            and str(item.get("request_model") or "")
            and str(item.get("response_model") or "")
            and str(item.get("response_id") or "")
        )

    routing_index = next(
        (
            index
            for index, item in enumerate(trace)
            if str(item.get("stage") or "")
            in {"intent_routing", "intent_routing_repair"}
            and valid(item)
        ),
        None,
    )
    narration_index = next(
        (
            index
            for index, item in enumerate(trace)
            if str(item.get("stage") or "") == "tool_evidence" and valid(item)
        ),
        None,
    )
    repair_indices = [
        index
        for index, item in enumerate(trace)
        if str(item.get("stage") or "") == "tool_evidence_repair"
    ]
    if (
        routing_index is None
        or narration_index is None
        or narration_index <= routing_index
        or (
            repair_indices
            and (
                repair_indices[-1] <= narration_index
                or not valid(trace[repair_indices[-1]])
            )
        )
    ):
        raise RuntimeError("product_llm_trace_missing_real_two_stage_evidence")


def record_product_chat(
    *,
    success: bool,
    stage: str,
    error: BaseException | None = None,
    trace: List[Dict[str, Any]] | None = None,
) -> None:
    if success:
        validate_product_llm_trace(list(trace or []))
    now = _utc_now()
    update: Dict[str, Any] = {
        "product_chat_last_success": bool(success),
        "product_chat_last_stage": str(stage),
    }
    if success:
        update.update(
            {
                "product_chat_last_success_at": now,
                "product_chat_last_error": None,
            }
        )
    else:
        update.update(
            {
                "product_chat_last_error_at": now,
                "product_chat_last_error": (
                    f"{type(error).__name__}:{error}" if error is not None else "unknown"
                ),
            }
        )
    _update_runtime_status(update)


def llm_status() -> Dict[str, Any]:
    client = LLMClient()
    configured, reason = client.available()
    with _STATUS_LOCK:
        runtime = {**_RUNTIME_STATUS, **_read_persisted_runtime_status()}
    success_at = None
    try:
        success_at = datetime.fromisoformat(
            str(runtime.get("product_chat_last_success_at") or "").replace("Z", "+00:00")
        )
        if success_at.tzinfo is None:
            success_at = success_at.replace(tzinfo=timezone.utc)
    except Exception:
        success_at = None
    verification_age_sec = (
        max(0.0, (datetime.now(timezone.utc) - success_at).total_seconds())
        if success_at is not None
        else None
    )
    verification_fresh = bool(
        verification_age_sec is not None
        and verification_age_sec <= _PRODUCT_VERIFICATION_MAX_AGE_SEC
    )
    if not configured:
        verification = "not_configured"
    elif runtime.get("product_chat_last_success") is False:
        verification = "error"
    elif runtime.get("product_chat_last_success") is True and verification_fresh:
        verification = "ready"
    elif runtime.get("product_chat_last_success") is True:
        verification = "stale"
    else:
        verification = "unverified"
    return {
        "available": bool(configured and runtime.get("last_call_success") is not False),
        "configured": bool(configured),
        "configuration_reason": reason,
        "verification": verification,
        "verification_fresh": verification_fresh,
        "verification_age_sec": (
            round(verification_age_sec, 1) if verification_age_sec is not None else None
        ),
        "verification_max_age_sec": _PRODUCT_VERIFICATION_MAX_AGE_SEC,
        "transport_verification": (
            "error"
            if runtime.get("last_call_success") is False
            else "ready"
            if runtime.get("last_call_success") is True
            else "unverified"
        ),
        "base_url": client.base_url or None,
        "model": client.model,
        **runtime,
    }


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

    def _post_payload(
        self,
        url: str,
        payload: Dict[str, Any],
        *,
        budget_stage: str,
        payload_limit_bytes: int | None,
        payload_compressed: bool,
        compression_steps: List[str] | None = None,
    ):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        data, _ = encode_llm_payload(
            payload,
            stage=budget_stage,
            limit_bytes=payload_limit_bytes,
            compressed=payload_compressed,
            compression_steps=compression_steps,
        )
        timeout = None if (isinstance(self.timeout, (int, float)) and self.timeout <= 0) else self.timeout
        return requests.post(url, headers=headers, data=data, timeout=timeout)

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        temperature: float = 0.2,
        stream: bool = False,
        json_mode: bool = False,
        extra: Optional[Dict[str, Any]] = None,
        budget_stage: str = "llm_chat",
        payload_limit_bytes: int | None = None,
        payload_compressed: bool = False,
        compression_steps: List[str] | None = None,
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
        started_at = monotonic()
        resp = None
        try:
            resp = self._post_payload(
                url,
                payload,
                budget_stage=budget_stage,
                payload_limit_bytes=payload_limit_bytes,
                payload_compressed=payload_compressed,
                compression_steps=compression_steps,
            )
            resp.raise_for_status()
            obj = resp.json()
        except Exception as ex:  # noqa: BLE001
            _record_call(
                success=False,
                started_at=started_at,
                http_status=getattr(resp, "status_code", None),
                error=ex,
                stage=budget_stage,
                request_model=self.model,
            )
            raise
        _record_call(
            success=True,
            started_at=started_at,
            http_status=resp.status_code,
            response=obj,
            stage=budget_stage,
            request_model=self.model,
        )
        return obj

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
        budget_stage: str = "llm_tool_call",
        payload_limit_bytes: int | None = None,
        payload_compressed: bool = False,
        compression_steps: List[str] | None = None,
    ) -> Dict[str, Any]:
        ok, reason = self.available()
        if not ok:
            raise RuntimeError(f"LLM 未就绪：{reason}")

        url = self.base_url.rstrip("/") + "/chat/completions"
        request_model = model or self.model or "deepseek-v4-flash"
        payload: Dict[str, Any] = {
            "model": request_model,
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
        started_at = monotonic()
        resp = None
        try:
            resp = self._post_payload(
                url,
                payload,
                budget_stage=budget_stage,
                payload_limit_bytes=payload_limit_bytes,
                payload_compressed=payload_compressed,
                compression_steps=compression_steps,
            )
            resp.raise_for_status()
            obj = resp.json()
        except Exception as ex:  # noqa: BLE001
            _record_call(
                success=False,
                started_at=started_at,
                http_status=getattr(resp, "status_code", None),
                error=ex,
                stage=budget_stage,
                request_model=request_model,
            )
            raise
        _record_call(
            success=True,
            started_at=started_at,
            http_status=resp.status_code,
            response=obj,
            stage=budget_stage,
            request_model=request_model,
        )
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
            # DeepSeek Beta rejects `tool_choice` while thinking mode is enabled.
            thinking=thinking if thinking is not None else {"type": "disabled"},
            budget_stage="agent_routing",
            payload_limit_bytes=ROUTING_PAYLOAD_LIMIT_BYTES,
            payload_compressed=True,
            compression_steps=["deduplicate", "summarize", "reference"],
        )
