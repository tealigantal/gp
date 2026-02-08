from __future__ import annotations

from .router_llm import LLMRouter, Route


def get_router() -> LLMRouter:
    """Single decision point: return the LLM router.

    The LLM decides which tool to invoke from user input and context.
    If the LLM is not configured, the router will gracefully fall back to `help`.
    """
    return LLMRouter()


def route_text(query: str, state) -> Route:  # noqa: ANN001
    """Delegate routing to the LLM router exclusively.

    No local rule-based branching here; the LLM is responsible for
    returning a JSON with {tool, args, confidence}.
    """
    router = get_router()
    return router.route_text(query, state)

