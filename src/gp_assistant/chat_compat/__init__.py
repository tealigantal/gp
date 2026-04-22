from __future__ import annotations

import sys

from ..chat import (
    render,
    session_store,
    event_store,
    refresh_service,
    orchestrator,
    run_service,
    tool_registry,
    assistant_bundle,
    context_builder,
    deepseek_agent,
    archive_legacy_threads,
    agent_tools,
)

for _name, _module in {
    "render": render,
    "session_store": session_store,
    "event_store": event_store,
    "refresh_service": refresh_service,
    "orchestrator": orchestrator,
    "run_service": run_service,
    "tool_registry": tool_registry,
    "assistant_bundle": assistant_bundle,
    "context_builder": context_builder,
    "deepseek_agent": deepseek_agent,
    "archive_legacy_threads": archive_legacy_threads,
    "agent_tools": agent_tools,
}.items():
    sys.modules[f"{__name__}.{_name}"] = _module
    globals()[_name] = _module

__all__ = [
    "render",
    "session_store",
    "event_store",
    "refresh_service",
    "orchestrator",
    "run_service",
    "tool_registry",
    "assistant_bundle",
    "context_builder",
    "deepseek_agent",
    "archive_legacy_threads",
    "agent_tools",
]
