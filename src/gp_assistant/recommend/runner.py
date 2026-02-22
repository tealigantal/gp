# src/gp_assistant/recommend/runner.py
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

    # aliases
    alias = {
        "prod": "default",
        "live": "default",
        "mock": "dev",
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
        out["debug"].setdefault("mode", m)
    return out


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