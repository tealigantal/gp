# 简介：Agent 运行态封装。包含 session_id、配置、上下文与历史，
# 便于在无服务模式下复用核心能力。
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, List

from ..core.config import AppConfig, load_config


@dataclass
class State:
    session_id: str = "default"
    config: AppConfig = field(default_factory=load_config)
    context: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)
