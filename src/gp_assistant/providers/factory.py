from __future__ import annotations

from typing import Tuple

from ..core.config import load_config
from ..core.logging import logger
from .akshare_provider import AkShareProvider
from .official_provider import OfficialProvider
from .base import MarketDataProvider


def get_provider() -> MarketDataProvider:
    """Single decision point for provider selection and fallback.

    Rules:
    - DATA_PROVIDER env/config chooses provider; default akshare.
    - If official is chosen but credentials missing, auto downgrade to akshare
      with a clear log message.
    """
    cfg = load_config()
    choice = cfg.provider.data_provider
    if choice == "official":
        official = OfficialProvider(api_key=cfg.provider.official_api_key)
        hc = official.healthcheck()
        if not hc.get("ok"):
            logger.warning(
                "官方 provider 未就绪(%s)，已自动降级到 akshare", hc.get("reason")
            )
            return AkShareProvider()
        return official
    # default
    return AkShareProvider()


def provider_health() -> dict:
    # Return both the chosen provider and its health for diagnostics
    p = get_provider()
    hc = p.healthcheck()
    return {"selected": p.name, **hc}

