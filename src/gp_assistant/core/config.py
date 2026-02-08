from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

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


def load_config() -> AppConfig:
    # Keep simple: env only for now; yaml hook reserved here if needed later.
    # If a configs/gp.yaml exists, we could merge, but per requirements avoid
    # spreading defaults; keep single point here.
    _ = configs_dir()  # ensure exists
    return AppConfig()
