# 简介：数据源选择工厂。按偏好与健康检查在 official/local/akshare 间选择，
# 提供 provider_health 概览。
from __future__ import annotations

from typing import Literal
import os
from ..core.config import load_config
from ..core.logging import logger
from .akshare_provider import AkShareProvider
from .official_provider import OfficialProvider
from .local_provider import LocalParquetProvider
from .base import MarketDataProvider


def get_provider(prefer: Literal["local", "online", "auto", None] = None) -> MarketDataProvider:
    """Provider selection with explicit preference and clear fallback chain.

    Preference order:
    - prefer=="local": Local if healthy, else fallback to online
    - prefer=="online": Official (if selected and healthy) else AkShare else Local
    - prefer==None/"auto": Official if healthy (when selected), else Local if healthy, else AkShare

    An environment variable `GP_PREFER_LOCAL=1` only applies when prefer is None.
    """
    cfg = load_config()
    choice = cfg.provider.data_provider

    # Handle env only when CLI didn't specify
    if prefer is None:
        if os.getenv("GP_PREFER_LOCAL", "").lower() in {"1", "true", "yes"}:
            prefer = "local"
        else:
            prefer = "auto"

    # Providers
    local = LocalParquetProvider()
    ak = AkShareProvider()
    off = OfficialProvider(api_key=cfg.provider.official_api_key)

    local_hc = local.healthcheck()
    ak_hc = ak.healthcheck()
    off_hc = off.healthcheck() if choice == "official" else {"ok": False, "reason": "not-selected"}

    if prefer == "local":
        if local_hc.get("ok"):
            return local
        # try online fallbacks
        if off_hc.get("ok"):
            return off
        if ak_hc.get("ok"):
            return ak
        return local  # last resort

    if prefer == "online":
        if off_hc.get("ok"):
            return off
        if ak_hc.get("ok"):
            return ak
        # fallback to local if available
        if local_hc.get("ok"):
            return local
        return ak

    # AUTO
    if off_hc.get("ok"):
        return off
    if local_hc.get("ok"):
        return local
    if ak_hc.get("ok"):
        return ak
    # final fallback
    logger.warning("所有数据源不可用，返回 AkShare 以暴露错误")
    return ak


def provider_health() -> dict:
    p = get_provider()
    hc = p.healthcheck()
    return {"selected": p.name, **hc}
