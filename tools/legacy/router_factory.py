from __future__ import annotations

from .router_llm import LLMRouter, Route


def get_router() -> LLMRouter:
    return LLMRouter()


def route_text(query: str, state) -> Route:  # noqa: ANN001
    router = get_router()
    return router.route_text(query, state)

