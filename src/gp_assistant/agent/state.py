from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any

from ..core.config import AppConfig, load_config


@dataclass
class State:
    session_id: str = "default"
    config: AppConfig = field(default_factory=load_config)
    context: Dict[str, Any] = field(default_factory=dict)

