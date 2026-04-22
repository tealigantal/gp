# src/gp_assistant/recommend/runner.py
"""
推荐“多模式”路由器。

用法：
- 默认：mode 为空 => 根据配置决定（dev_mode -> dev，否则 default）
- 显式：POST /api/recommend { "mode": "dev" } 或 "default" 或你未来新增的模式名
- 新增模式：在 src/gp_assistant/recommend/modes/<mode>.py 里实现 run(...)
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from typing import Any, Dict, List, Optional

from ..core.config import load_config
from ..core.errors import APIError
from . import agent as default_agent

_SAFE_MODE = re.compile(r"^[a-z0-9_]+$")


def resolve_mode(request_mode: Optional[str]) -> str:
    cfg = load_config()

    m = (request_mode or "").strip().lower()
    if not m:
        m = (cfg.recommend_mode or ("dev" if cfg.dev_mode else "default")).strip().lower()

    alias = {
        "prod": "default",
        "live": "default",
        "real": "default",
        "mock": "dev",
        "fixture": "dev",
    }
    return alias.get(m, m)


def run(
    *,
    mode: Optional[str] = None,
    date: Optional[str] = None,
    topk: int = 3,
    universe: str = "auto",
    symbols: Optional[List[str]] = None,
    risk_profile: str = "normal",
) -> Dict[str, Any]:
    m = resolve_mode(mode)

    if m == "default":
        return default_agent.run(date=date, topk=topk, universe=universe, symbols=symbols, risk_profile=risk_profile)

    if not _SAFE_MODE.fullmatch(m):
        raise APIError(status_code=400, message="invalid recommend mode", detail={"mode": m})

    try:
        mod = importlib.import_module(f"gp_assistant.recommend.modes.{m}")
    except ModuleNotFoundError as e:
        raise APIError(status_code=400, message="unknown recommend mode", detail={"mode": m}) from e

    fn = getattr(mod, "run", None)
    if not callable(fn):
        raise APIError(status_code=500, message="recommend mode missing run()", detail={"mode": m})

    out = fn(date=date, topk=topk, universe=universe, symbols=symbols, risk_profile=risk_profile)

    if isinstance(out, dict):
        out.setdefault("debug", {})
        if isinstance(out["debug"], dict):
            out["debug"].setdefault("mode", m)
    return out  # type: ignore[return-value]


def list_modes() -> List[str]:
    out = ["default"]
    try:
        from . import modes as modes_pkg  # type: ignore

        for it in pkgutil.iter_modules(modes_pkg.__path__):  # type: ignore[attr-defined]
            if it.name.startswith("_"):
                continue
            out.append(it.name)
    except Exception:
        pass
    return sorted(set(out))