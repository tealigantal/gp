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
class SerenityConfig:
    mode: str = os.getenv("GP_SERENITY_MODE", "auto").strip().lower()
    max_weight: float = float(os.getenv("GP_SERENITY_MAX_WEIGHT", "0.08"))
    update_mature_days: int = int(os.getenv("GP_SERENITY_UPDATE_MATURE_DAYS", "5"))
    eval_window_days: int = int(os.getenv("GP_SERENITY_EVAL_WINDOW_DAYS", "60"))
    request_timeout_sec: float = float(os.getenv("GP_SERENITY_REQUEST_TIMEOUT_SEC", "15"))
    page_size: int = int(os.getenv("GP_SERENITY_PAGE_SIZE", "30"))
    page_budget: int = int(os.getenv("GP_SERENITY_PAGE_BUDGET", "10"))
    bootstrap_lookback_days: int = int(os.getenv("GP_SERENITY_BOOTSTRAP_LOOKBACK_DAYS", "30"))
    evidence_ttl_days: int = int(os.getenv("GP_SERENITY_EVIDENCE_TTL_DAYS", "10"))
    pdf_max_bytes: int = int(os.getenv("GP_SERENITY_PDF_MAX_BYTES", str(15 * 1024 * 1024)))
    cost_window: int = int(os.getenv("GP_SERENITY_COST_WINDOW", "20"))
    ewma_alpha: float = float(os.getenv("GP_SERENITY_EWMA_ALPHA", "0.30"))
    request_spacing_sec: float = float(os.getenv("GP_SERENITY_REQUEST_SPACING_SEC", "1"))
    content_revalidate_hours: float = float(os.getenv("GP_SERENITY_CONTENT_REVALIDATE_HOURS", "6"))
    target_fallback_ttl_sec: int = int(os.getenv("GP_SERENITY_TARGET_FALLBACK_TTL_SEC", "3600"))
    circuit_breaker_sec: int = int(os.getenv("GP_SERENITY_CIRCUIT_BREAKER_SEC", "1800"))
    lease_sec: int = int(os.getenv("GP_SERENITY_LEASE_SEC", "180"))

    def __post_init__(self) -> None:
        if self.mode not in {"off", "reference", "auto"}:
            self.mode = "off"
        self.max_weight = max(0.0, min(0.08, float(self.max_weight)))
        self.update_mature_days = max(1, int(self.update_mature_days))
        self.eval_window_days = max(20, int(self.eval_window_days))
        self.page_size = max(1, min(100, int(self.page_size)))
        self.page_budget = max(1, min(50, int(self.page_budget)))
        self.evidence_ttl_days = max(1, min(90, int(self.evidence_ttl_days)))
        self.cost_window = max(3, min(100, int(self.cost_window)))
        self.ewma_alpha = max(0.01, min(1.0, float(self.ewma_alpha)))
        self.content_revalidate_hours = max(1.0, min(72.0, float(self.content_revalidate_hours)))
        self.target_fallback_ttl_sec = max(60, min(86400, int(self.target_fallback_ttl_sec)))


@dataclass
class AppConfig:
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    serenity: SerenityConfig = field(default_factory=SerenityConfig)

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

    request_timeout_sec: int = int(os.getenv("GP_REQUEST_TIMEOUT_SEC", "30"))
    default_volume_unit: str = os.getenv("GP_DEFAULT_VOLUME_UNIT", "share").lower()

    # Timezone
    timezone: str = os.getenv("TZ", "Asia/Shanghai")

    # LLM
    llm_base_url: Optional[str] = os.getenv("LLM_BASE_URL")
    llm_api_key: Optional[str] = os.getenv("LLM_API_KEY")
    chat_model: str = os.getenv("CHAT_MODEL", "deepseek-chat")
    agent_model: str = os.getenv("AGENT_MODEL", os.getenv("CHAT_MODEL", "deepseek-chat"))
    agent_max_tool_rounds: int = int(os.getenv("GP_AGENT_MAX_TOOL_ROUNDS", "3"))

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
    intraday_runtime_enabled: bool = _truthy(os.getenv("GP_INTRADAY_RUNTIME_ENABLED", "1"))
    intraday_fetch_workers: int = int(os.getenv("GP_INTRADAY_FETCH_WORKERS", "3"))
    intraday_fetch_timeout_sec: int = int(os.getenv("GP_INTRADAY_FETCH_TIMEOUT_SEC", "180"))
    intraday_fetch_retry_missing: bool = _truthy(os.getenv("GP_INTRADAY_FETCH_RETRY_MISSING", "1"))
    intraday_min5_refresh_sec: int = int(os.getenv("GP_INTRADAY_MIN5_REFRESH_SEC", "120"))
    intraday_fetch_budget_sec: int = int(os.getenv("GP_INTRADAY_FETCH_BUDGET_SEC", "110"))
    intraday_symbol_cooldown_sec: int = int(os.getenv("GP_INTRADAY_SYMBOL_COOLDOWN_SEC", "90"))
    intraday_model_max_stale_sec: int = int(os.getenv("GP_INTRADAY_MODEL_MAX_STALE_SEC", "600"))
    intraday_core_first: bool = _truthy(os.getenv("GP_INTRADAY_CORE_FIRST", "1"))
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
