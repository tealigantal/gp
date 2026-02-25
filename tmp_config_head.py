# src/gp_assistant/core/config.py
"""
搴旂敤閰嶇疆涓績锛堢幆澧冨彉閲?-> 缁熶竴閰嶇疆瀵硅薄锛夈€?
鐩爣锛?- 鎶娾€滆繍琛屾ā寮?/ 寮€鍙戣€呮ā寮?/ 鎺ㄨ崘妯″紡鈥濈瓑寮€鍏虫敹鍙ｅ埌涓€涓湴鏂癸紱
- 渚?server/recommend/providers/chat 绛夋ā鍧楃粺涓€璇诲彇锛?- 榛樿涓嶇牬鍧忕嚎涓婅涓猴細涓嶈缃?GP_DEV_MODE/GP_RUN_MODE 鏃讹紝淇濇寔鐪熷疄鏁版嵁涓庨粯璁ゆ帹鑽愰摼璺€?"""

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
    """鏁版嵁婧愰厤缃紙factory 鎸夋閫夋嫨 provider锛?""

    data_provider: str = os.getenv("DATA_PROVIDER", "akshare").lower()
    official_api_key: Optional[str] = os.getenv("OFFICIAL_API_KEY")


@dataclass
class AppConfig:
    provider: ProviderConfig = field(default_factory=ProviderConfig)

    # -------------------------
    # Run mode / developer mode
    # -------------------------
    # prod|dev锛坉ev 鏃堕粯璁ゅ紑鍚?dev_mode锛?    run_mode: str = os.getenv("GP_RUN_MODE", "prod").lower()

    # 鏄惧紡寮€鍙戣€呮ā寮忓紑鍏筹紙浼樺厛绾ч珮锛?    dev_mode: bool = _truthy(os.getenv("GP_DEV_MODE", "0"))

    # 鎺ㄨ崘妯″紡锛歞efault|dev|<浣犳湭鏉ユ柊澧炵殑妯″紡鍚?
    # 涓虹┖ => auto锛坉ev_mode -> dev锛屽惁鍒?default锛?    recommend_mode: str = os.getenv("GP_RECOMMEND_MODE", "").lower()

    # 寮€鍙戞ā寮忥細鍥哄畾杈撳嚭鐨勯粯璁?symbols锛堢敤浜庡墠绔崱鐗?鍒楄〃锛?    dev_symbols: List[str] = field(default_factory=lambda: ["000001", "000333", "600519"])
    dev_ohlcv_len: int = int(os.getenv("GP_DEV_OHLCV_LEN", "90"))

    # -------------------------
    # Defaults / knobs
    # -------------------------
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

    # Strict real data only (no synthetic/degrade). Default ON (per your current repo behavior)
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

    # Parallelism for candidate generation
    # 0 or negative => auto (use CPU-based default)
    parallel_workers: int = int(os.getenv("GP_PARALLEL_WORKERS", "0"))

    # Cache refresh TTL for market data (seconds). Within TTL, skip network refresh and serve cache.
    cache_refresh_ttl_sec: int = int(os.getenv("GP_CACHE_REFRESH_TTL_SEC", "300"))


def load_config() -> AppConfig:
    """璇诲彇鐜鍙橀噺骞跺仛娲剧敓/鏍￠獙銆?""
    _ = configs_dir()  # ensure exists

    cfg = AppConfig()

    # Derive dev_mode from run_mode
    if cfg.run_mode in {"dev", "development"}:
        cfg.dev_mode = True

    # dev symbols override
    env_syms = _split_csv(os.getenv("GP_DEV_SYMBOLS"))
    if env_syms:
        cfg.dev_symbols = env_syms

    # akshare route priorities override
    spot = _split_csv(os.getenv("AK_SPOT_PRIORITY"))
    daily = _split_csv(os.getenv("AK_DAILY_PRIORITY"))
    if spot:
        cfg.ak_spot_priority = spot
    if daily:
        cfg.ak_daily_priority = daily

    # default recommend_mode
    if not cfg.recommend_mode:
        cfg.recommend_mode = "dev" if cfg.dev_mode else "default"

    # Validate timezone
    try:
        _ = zoneinfo.ZoneInfo(cfg.timezone)
    except Exception:
        cfg.timezone = "Asia/Shanghai"

    return cfg
