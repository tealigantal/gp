from __future__ import annotations

from dataclasses import dataclass
from typing import List

from gp_research.search import search as _search


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    source: str


def search(query: str, recency_days: int = 14, top_k: int = 8, provider: str | None = None) -> List[SearchResult]:
    res = _search(query, recency_days=recency_days, top_k=top_k, provider=provider)
    # Map to local dataclass for compatibility
    return [SearchResult(url=r.url, title=r.title, snippet=r.snippet, source=r.source) for r in res]

