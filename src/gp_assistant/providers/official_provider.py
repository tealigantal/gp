from __future__ import annotations

from typing import Dict, Any
import pandas as pd

from ..core.errors import MissingCredentialsError
from .base import MarketDataProvider


class OfficialProvider(MarketDataProvider):
    name = "official"

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def _ensure(self) -> None:
        if not self.api_key:
            raise MissingCredentialsError(
                provider=self.name,
                hint="请设置 OFFICIAL_API_KEY 环境变量或在配置中提供",
            )

    def get_daily(self, symbol: str, start: str | None, end: str | None) -> pd.DataFrame:  # noqa: D401
        self._ensure()
        # Placeholder: real implementation to be added later
        raise MissingCredentialsError(self.name, "官方数据源占位实现，未配置凭证")

    def healthcheck(self) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "name": self.name,
                "ok": False,
                "reason": "OFFICIAL_API_KEY 未配置",
            }
        return {"name": self.name, "ok": True, "reason": None}

