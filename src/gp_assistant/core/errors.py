# 简介：统一异常类型定义。包含 APIError、通用包内错误、数据源错误、
# 以及凭证缺失错误，用于 HTTP 与内部逻辑的标准化报错。
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class APIError(Exception):
    status_code: int
    message: str
    detail: Optional[Dict[str, Any]] = None

    def to_json(self) -> Dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "detail": self.detail or {},
            }
        }


class GPAssistantError(Exception):
    pass


class DataProviderError(Exception):
    def __init__(self, message: str, *, symbol: Optional[str] = None):
        super().__init__(message)
        self.symbol = symbol


class MissingCredentialsError(GPAssistantError):
    def __init__(self, provider: str, hint: Optional[str] = None):
        msg = f"缺少凭证: {provider}"
        if hint:
            msg = f"{msg}（{hint}）"
        super().__init__(msg)
        self.provider = provider
        self.hint = hint
