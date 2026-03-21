# 简介：策略库元信息与统一接口封装，汇总各具体策略以便统一调用与编排。
from __future__ import annotations

from typing import Dict, Any, Callable

# Registry mapping id -> module
REGISTRY: Dict[str, Any] = {}

# Optional: strategy metadata for champion eligibility and routing
# Note: additive and safe defaults; individual strategies can be updated here
# without changing their modules. Keys:
# - family: trend|breakout|mean_reversion|structure
# - direction: long|short|contra
# - live_enabled: bool
# - prefer_observation_only: bool
# - champion_eligible: bool
METADATA: Dict[str, Dict[str, Any]] = {}


def register(name: str, mod: Any) -> None:
    REGISTRY[name] = mod


def get(name: str) -> Any:
    return REGISTRY[name]


# Eager import strategies to ensure availability
from .strategies import s01_bias6_crossup as S1  # noqa: E402,F401
from .strategies import s02_rsi2 as S2  # noqa: E402,F401
from .strategies import s03_squeeze as S3  # noqa: E402,F401
from .strategies import s04_turtle_soup as S4  # noqa: E402,F401
from .strategies import s05_ma20_retracement as S5  # noqa: E402,F401
from .strategies import s06_breakout_pullback as S6  # noqa: E402,F401
from .strategies import s07_nr7_contraction as S7  # noqa: E402,F401
from .strategies import s08_volratio_surge as S8  # noqa: E402,F401
from .strategies import s09_chip_support as S9  # noqa: E402,F401
from .strategies import s10_gap_fade as S10  # noqa: E402,F401
from .strategies import s11_rsi2_extreme as S11  # noqa: E402,F401
from .strategies import s12_avwap as S12  # noqa: E402,F401
from .strategies import s13_squeeze_release as S13  # noqa: E402,F401
from .strategies import s14_turtle_soup_plus as S14  # noqa: E402,F401

register("S1", S1)
register("S2", S2)
register("S3", S3)
register("S4", S4)
register("S5", S5)
register("S6", S6)
register("S7", S7)
register("S8", S8)
register("S9", S9)
register("S10", S10)
register("S11", S11)
register("S12", S12)
register("S13", S13)
register("S14", S14)

# Populate metadata with conservative assumptions; these can be tuned later.
# The goal is to downweight non-live-long candidates without removing them.
METADATA.update({
    "S1": {"family": "trend", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S2": {"family": "mean_reversion", "direction": "long", "live_enabled": True, "prefer_observation_only": True, "champion_eligible": False},
    "S3": {"family": "breakout", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S4": {"family": "mean_reversion", "direction": "contra", "live_enabled": True, "prefer_observation_only": True, "champion_eligible": False},
    "S5": {"family": "trend", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S6": {"family": "trend", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S7": {"family": "breakout", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S8": {"family": "momentum", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S9": {"family": "structure", "direction": "long", "live_enabled": True, "prefer_observation_only": True, "champion_eligible": True},
    "S10": {"family": "mean_reversion", "direction": "contra", "live_enabled": True, "prefer_observation_only": True, "champion_eligible": False},
    "S11": {"family": "mean_reversion", "direction": "long", "live_enabled": True, "prefer_observation_only": True, "champion_eligible": False},
    "S12": {"family": "structure", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S13": {"family": "breakout", "direction": "long", "live_enabled": True, "prefer_observation_only": False, "champion_eligible": True},
    "S14": {"family": "mean_reversion", "direction": "contra", "live_enabled": True, "prefer_observation_only": True, "champion_eligible": False},
})
