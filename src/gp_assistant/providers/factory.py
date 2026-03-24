# 简介：数据源选择工厂。按偏好与健康检查在 official/local/akshare 间选择，
# 提供 provider_health 概览。
from __future__ import annotations

from typing import Literal
import os
import time
import threading
from ..core.config import load_config
from ..core.logging import logger
from .akshare_provider import AkShareProvider
from .official_provider import OfficialProvider
from .local_provider import LocalParquetProvider
from .base import MarketDataProvider

# Provider singletons and healthcheck cache (avoid per-call construction/healthchecks in hot paths)
_PROVIDER_LOCK = threading.Lock()
_PROVIDER_SINGLETONS: dict[str, MarketDataProvider] = {}
_HEALTH_CACHE: dict[str, tuple[float, dict]] = {}


def _get_singletons(cfg) -> tuple[MarketDataProvider, MarketDataProvider, MarketDataProvider]:
    with _PROVIDER_LOCK:
        if not _PROVIDER_SINGLETONS:
            _PROVIDER_SINGLETONS["local"] = LocalParquetProvider()
            _PROVIDER_SINGLETONS["akshare"] = AkShareProvider(timeout_sec=cfg.request_timeout_sec)
            _PROVIDER_SINGLETONS["official"] = OfficialProvider(api_key=cfg.provider.official_api_key)
        else:
            # keep akshare timeout aligned with config (best effort)
            try:
                ak = _PROVIDER_SINGLETONS.get("akshare")
                if ak is not None:
                    try:
                        desired = int(cfg.request_timeout_sec)
                    except Exception:
                        desired = 20
                    if desired <= 0:
                        desired = 10
                    if getattr(ak, "timeout_sec", None) != desired:
                        setattr(ak, "timeout_sec", desired)
            except Exception:
                pass
        return (
            _PROVIDER_SINGLETONS["local"],
            _PROVIDER_SINGLETONS["akshare"],
            _PROVIDER_SINGLETONS["official"],
        )


def _health_cached(p: MarketDataProvider) -> dict:
    try:
        ttl = int(os.getenv("GP_PROVIDER_HEALTH_TTL_SEC", "60"))
    except Exception:
        ttl = 60
    key = getattr(p, "name", p.__class__.__name__)
    now = time.time()
    cached = _HEALTH_CACHE.get(key)
    if cached is not None:
        ts, hc = cached
        if hc is not None and (now - float(ts)) <= ttl:
            return hc
    hc = p.healthcheck()
    _HEALTH_CACHE[key] = (now, hc)
    return hc


def get_provider(prefer: Literal["local", "online", "auto", "akshare", "official", None] = None) -> MarketDataProvider:
    """Provider selection with explicit preference and clear fallback chain.

    Preference order:
    - prefer=="local": Local if healthy, else fallback to online
    - prefer=="online": Official (if selected and healthy) else AkShare else Local
    - prefer==None/"auto": Official if healthy (when selected), else Local if healthy, else AkShare

    An environment variable `GP_PREFER_LOCAL=1` only applies when prefer is None.
    """
    cfg = load_config()
    choice = (cfg.provider.data_provider or "auto").lower()

    # Handle env only when CLI didn't specify
    if prefer is None:
        if os.getenv("GP_PREFER_LOCAL", "").lower() in {"1", "true", "yes"}:
            prefer = "local"
        else:
            prefer = "auto"

    local, ak, off = _get_singletons(cfg)

    # When user explicitly sets DATA_PROVIDER, honor it strictly (no healthchecks in hot paths)
    if choice == "akshare":
        return ak
    if choice == "local":
        return local
    if choice == "official":
        return off

    local_hc = _health_cached(local)
    ak_hc = _health_cached(ak)
    off_hc = {"ok": False, "reason": "not-selected"}

    if prefer == "local":
        if local_hc.get("ok"):
            return local
        # try online fallbacks
        if off_hc.get("ok"):
            return off
        if ak_hc.get("ok"):
            return ak
        return local

    if prefer == "online":
        if off_hc.get("ok"):
            return off
        if ak_hc.get("ok"):
            return ak
        # fallback to local if available
        if local_hc.get("ok"):
            return local
        return ak

    # AUTO (or unknown)
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
