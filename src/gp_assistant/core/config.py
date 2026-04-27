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

    # Run mode / developer mode
    run_mode: str = os.getenv("GP_RUN_MODE", "prod").lower()
    dev_mode: bool = _truthy(os.getenv("GP_DEV_MODE", "0"))

    # Recommend mode
    recommend_mode: str = os.getenv("GP_RECOMMEND_MODE", "").lower()

    # Dev fixtures
    dev_symbols: List[str] = field(default_factory=lambda: ["000001", "000333", "600519"])
    dev_ohlcv_len: int = int(os.getenv("GP_DEV_OHLCV_LEN", "90"))

    # Defaults / knobs
    default_universe: List[str] = field(default_factory=lambda: ["000001", "000002", "000333", "600519"])

    request_timeout_sec: int = int(os.getenv("GP_REQUEST_TIMEOUT_SEC", "20"))
    default_volume_unit: str = os.getenv("GP_DEFAULT_VOLUME_UNIT", "share").lower()

    # Timezone
    timezone: str = os.getenv("TZ", "Asia/Shanghai")

    # LLM
    llm_base_url: Optional[str] = os.getenv("LLM_BASE_URL")
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY")
    chat_model: str = os.getenv("CHAT_MODEL", "deepseek-chat")

    # AkShare routes (optional)
    ak_spot_priority: List[str] = field(default_factory=lambda: ["em", "sina"])
    ak_daily_priority: List[str] = field(default_factory=lambda: ["sina", "em", "tx"])
    # Spot refresh TTL (seconds) for memory cache hint
    ak_spot_refresh_ttl_sec: int = int(os.getenv("AK_SPOT_REFRESH_TTL_SEC", "30"))

    # Strict real data only (no synthetic/degrade)
    strict_real_data: bool = _truthy(os.getenv("STRICT_REAL_DATA", "1"))

    # Universe/dynamic pool knobs
    min_avg_amount: float = float(os.getenv("GP_MIN_AVG_AMOUNT", "5e8"))
    new_stock_days: int = int(os.getenv("GP_NEW_STOCK_DAYS", "60"))
    price_min: float = float(os.getenv("GP_PRICE_MIN", "2"))
    price_max: float = float(os.getenv("GP_PRICE_MAX", "500"))
    dynamic_pool_size: int = int(os.getenv("GP_DYNAMIC_POOL_SIZE", "200"))

    # Mainline restriction
    restrict_to_mainline: bool = _truthy(os.getenv("GP_RESTRICT_MAINLINE", "0"))
    mainline_top_n: int = int(os.getenv("GP_MAINLINE_TOP_N", "2"))
    mainline_mode: str = os.getenv("GP_MAINLINE_MODE", "auto")
    # Optional: require mainline to be present for tradeable
    require_mainline_for_tradeable: bool = _truthy(os.getenv("GP_REQUIRE_MAINLINE_FOR_TRADEABLE", "0"))

    # Diversification
    max_per_industry: int = int(os.getenv("GP_MAX_PER_INDUSTRY", "2"))

    # Tradeable thresholds
    tradeable_min_universe: int = int(os.getenv("GP_TRADEABLE_MIN_UNIVERSE", "50"))
    tradeable_min_candidates: int = int(os.getenv("GP_TRADEABLE_MIN_CANDIDATES", "20"))

    # Bands/windows knobs
    chip_window_bars: int = int(os.getenv("GP_CHIP_WINDOW_BARS", "120"))
    keyband_stale_threshold: int = int(os.getenv("GP_KEYBAND_STALE_BARS", "10"))
    keyband_recent_window: int = int(os.getenv("GP_KEYBAND_RECENT_WINDOW", "60"))
    bands_sanity_ratio: float = float(os.getenv("GP_BANDS_SANITY_RATIO", "3.0"))

    # Parallelism
    parallel_workers: int = int(os.getenv("GP_PARALLEL_WORKERS", "0"))

    # Cache TTL
    cache_refresh_ttl_sec: int = int(os.getenv("GP_CACHE_REFRESH_TTL_SEC", "300"))

    # Intraday pulse/worker
    intraday_fetch_workers: int = int(os.getenv("GP_INTRADAY_FETCH_WORKERS", "6"))
    intraday_fetch_timeout_sec: int = int(os.getenv("GP_INTRADAY_FETCH_TIMEOUT_SEC", "20"))
    intraday_poll_interval_sec: int = int(os.getenv("GP_INTRADAY_POLL_INTERVAL_SEC", "15"))
    intraday_benchmark_symbol: str = os.getenv("GP_INTRADAY_BENCHMARK", "000300")
    intraday_include_portfolio: bool = _truthy(os.getenv("GP_INTRADAY_INCLUDE_PORTFOLIO", "1"))
    intraday_slot_baseline_days: int = int(os.getenv("GP_INTRADAY_SLOT_BASELINE_DAYS", "20"))


def load_config() -> AppConfig:
    _ = configs_dir()  # ensure exists
    cfg = AppConfig()
    if cfg.run_mode in {"dev", "development"}:
        cfg.dev_mode = True
    env_syms = _split_csv(os.getenv("GP_DEV_SYMBOLS"))
    if env_syms:
        cfg.dev_symbols = env_syms
    spot = _split_csv(os.getenv("AK_SPOT_PRIORITY"))
    daily = _split_csv(os.getenv("AK_DAILY_PRIORITY"))
    if spot:
        cfg.ak_spot_priority = spot
    if daily:
        cfg.ak_daily_priority = daily
    if not cfg.recommend_mode:
        cfg.recommend_mode = "dev" if cfg.dev_mode else "default"
    try:
        _ = zoneinfo.ZoneInfo(cfg.timezone)
    except Exception:
        cfg.timezone = "Asia/Shanghai"
    return cfg
