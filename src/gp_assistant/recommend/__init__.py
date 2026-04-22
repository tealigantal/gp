from __future__ import annotations

"""Compatibility bridge for legacy ``gp_assistant.recommend`` imports.

The codebase was reorganized under ``gp_assistant.selection_engine`` but a
large portion of tests, scripts, and a few runtime paths still import the old
package name. Keep the public import surface stable by aliasing the retained
modules here instead of duplicating implementation.
"""

from importlib import import_module
import sys

_MODULE_ALIASES = (
    "agent",
    "announcements",
    "artifact_store",
    "calendar",
    "calibration",
    "candidate_gen",
    "chg_normalize",
    "compact_payload",
    "compare_service",
    "contracts",
    "datahub",
    "engine",
    "events",
    "mainline",
    "market_env",
    "modes",
    "refresh_service",
    "runner",
    "self_check",
    "self_check_contract",
    "strict_output",
    "theme_concept",
    "theme_hints",
    "theme_pool",
    "theme_pool_impl",
    "validators",
)

for _name in _MODULE_ALIASES:
    _module = import_module(f"gp_assistant.selection_engine.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _module
    globals()[_name] = _module

__all__ = list(_MODULE_ALIASES)
