# 简介：应用配置中心。读取环境变量，提供数据源偏好、默认标的集合、
# LLM/时区/超时等参数，供各模块统一访问。
# src/gp_assistant/core/config.py
from __future__ import annotations

import os
import zoneinfo
from dataclasses import dataclass, field
from typing import List, Optional

from .paths import configs_dir


def _truthy(v: str | None) -> bool:
    if v is None:
        return False
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_csv(v: str | None) -> List[str]:
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass
class ProviderConfig:
    data_provider: str = os.getenv("DATA_PROVIDER", "akshare").lower()
    official_api_key: Optional[str] = os.getenv("OFFICIAL_API_KEY")


@dataclass
class AppConfig:
    provider: ProviderConfig = field(default_factory=ProviderConfig)

    # ---- Run mode / developer mode ----
    run_mode: str = os.getenv("GP_RUN_MODE", "prod").lower()  # prod|dev
    dev_mode: bool = _truthy(os.getenv("GP_DEV_MODE", "0"))
    recommend_mode: str = os.getenv("GP_RECOMMEND_MODE", "").lower()  # empty => auto
    dev_symbols: List[str] = field(default_factory=lambda: ["000001", "000333", "600519"])
    dev_ohlcv_len: int = int(os.getenv("GP_DEV_OHLCV_LEN", "90"))

    # ---- Defaults ----
    default_universe: List[str] = field(
        default_factory=lambda: ["000001", "000002", "000333", "600519"]
    )

    # Additional knobs
    request_timeout_sec: int = int(os.getenv("GP_REQUEST_TIMEOUT_SEC", "20"))

    # Data defaults
    default_volume_unit: str = os.getenv("GP_DEFAULT_VOLUME_UNIT", "share").lower()

    # Timezone
    timezone: str = os.getenv("TZ", "Asia/Shanghai")

    # LLM
    llm_base_url: Optional[str] = os.getenv("LLM_BASE_URL")
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY")
    chat_model: str = os.getenv("CHAT_MODEL", "deepseek-chat")

    # Strict real data only (no synthetic/degrade).
    # Default ON per user requirement
    strict_real_data: bool = _truthy(os.getenv("STRICT_REAL_DATA", "1"))

    # Universe/dynamic pool knobs
    min_avg_amount: float = float(os.getenv("GP_MIN_AVG_AMOUNT", "5e8"))
    new_stock_days: int = int(os.getenv("GP_NEW_STOCK_DAYS", "60"))
    price_min: float = float(os.getenv("GP_PRICE_MIN", "2"))
    price_max: float = float(os.getenv("GP_PRICE_MAX", "500"))
    dynamic_pool_size: int = int(os.getenv("GP_DYNAMIC_POOL_SIZE", "200"))

    # Mainline restriction
    restrict_to_mainline: bool = _truthy(os.getenv("GP_RESTRICT_MAINLINE", "1"))
    mainline_top_n: int = int(os.getenv("GP_MAINLINE_TOP_N", "2"))
    mainline_mode: str = os.getenv("GP_MAINLINE_MODE", "auto")  # industry|concept|auto

    # Diversification
    max_per_industry: int = int(os.getenv("GP_MAX_PER_INDUSTRY", "2"))

    # Tradeable thresholds
    tradeable_min_universe: int = int(os.getenv("GP_TRADEABLE_MIN_UNIVERSE", "50"))
    tradeable_min_candidates: int = int(os.getenv("GP_TRADEABLE_MIN_CANDIDATES", "20"))


def load_config() -> AppConfig:
    _ = configs_dir()  # ensure exists

    cfg = AppConfig()

    # derive dev_mode from run_mode
    if cfg.run_mode in {"dev", "development"}:
        cfg.dev_mode = True

    # dev symbols override
    env_syms = _split_csv(os.getenv("GP_DEV_SYMBOLS"))
    if env_syms:
        cfg.dev_symbols = env_syms

    # default recommend_mode
    if not cfg.recommend_mode:
        cfg.recommend_mode = "dev" if cfg.dev_mode else "default"

    # Validate timezone
    try:
        _ = zoneinfo.ZoneInfo(cfg.timezone)
    except Exception:
        cfg.timezone = "Asia/Shanghai"

    return cfg