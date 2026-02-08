# 简介：应用配置中心。读取环境变量，提供数据源偏好、默认标的集合、
# LLM/时区/超时等参数，供各模块统一访问。
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional
import zoneinfo

from .paths import configs_dir


@dataclass
class ProviderConfig:
    data_provider: str = os.getenv("DATA_PROVIDER", "akshare").lower()
    official_api_key: Optional[str] = os.getenv("OFFICIAL_API_KEY")


@dataclass
class AppConfig:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    default_universe: List[str] = field(
        default_factory=lambda: ["000001", "000002", "000333", "600519"]
    )
    # Additional knobs (extendable):
    request_timeout_sec: int = int(os.getenv("GP_REQUEST_TIMEOUT_SEC", "20"))
    # Data defaults
    default_volume_unit: str = os.getenv("GP_DEFAULT_VOLUME_UNIT", "share").lower()
    # Timezone
    timezone: str = os.getenv("TZ", "Asia/Shanghai")
    # LLM
    llm_base_url: Optional[str] = os.getenv("LLM_BASE_URL")
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY")
    chat_model: str = os.getenv("CHAT_MODEL", "deepseek-chat")
    # Strict real data only (no synthetic/degrade). Default ON per user requirement
    strict_real_data: bool = os.getenv("STRICT_REAL_DATA", "1").lower() in {"1", "true", "yes"}
    # Universe/dynamic pool knobs
    min_avg_amount: float = float(os.getenv("GP_MIN_AVG_AMOUNT", "5e8"))
    new_stock_days: int = int(os.getenv("GP_NEW_STOCK_DAYS", "60"))
    price_min: float = float(os.getenv("GP_PRICE_MIN", "2"))
    price_max: float = float(os.getenv("GP_PRICE_MAX", "500"))
    dynamic_pool_size: int = int(os.getenv("GP_DYNAMIC_POOL_SIZE", "200"))
    # Mainline restriction
    restrict_to_mainline: bool = os.getenv("GP_RESTRICT_MAINLINE", "1").lower() in {"1", "true", "yes"}
    mainline_top_n: int = int(os.getenv("GP_MAINLINE_TOP_N", "2"))
    mainline_mode: str = os.getenv("GP_MAINLINE_MODE", "auto")  # industry|concept|auto
    # Diversification
    max_per_industry: int = int(os.getenv("GP_MAX_PER_INDUSTRY", "2"))


def load_config() -> AppConfig:
    # Keep simple: env only for now; yaml hook reserved here if needed later.
    # If a configs/gp.yaml exists, we could merge, but per requirements avoid
    # spreading defaults; keep single point here.
    _ = configs_dir()  # ensure exists
    cfg = AppConfig()
    # Validate timezone
    try:
        _ = zoneinfo.ZoneInfo(cfg.timezone)
    except Exception:
        cfg.timezone = "Asia/Shanghai"
    return cfg
