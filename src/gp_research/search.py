from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import re
import time
import urllib.parse
import requests


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    source: str  # provider id


class BaseSearchProvider:
    def search(self, query: str, recency_days: int = 14, top_k: int = 8) -> List[SearchResult]:
        raise NotImplementedError


class MockSearchProvider(BaseSearchProvider):
    def search(self, query: str, recency_days: int = 14, top_k: int = 8) -> List[SearchResult]:
        return [
            SearchResult(
                url="https://example.com/mock/market",
                title="Mock 市场综述",
                snippet=f"[mock] 近{recency_days}日市场偏震荡，资金轮动明显。query={query}",
                source="mock",
            )
        ]


class DuckduckgoSearchProvider(BaseSearchProvider):
    BASE = "https://duckduckgo.com/html/"

    def search(self, query: str, recency_days: int = 14, top_k: int = 8) -> List[SearchResult]:
        # Use simple HTML endpoint to avoid API keys; parse roughly
        q = f"site:finance.sina.com.cn OR site:eastmoney.com A股 市场 板块 资金 {query}"
        try:
            params = {"q": q}
            r = requests.get(self.BASE, params=params, timeout=10)
            r.raise_for_status()
            html = r.text
            # crude parsing for result blocks
            # Titles like: <a rel="nofollow" class="result__a" href="/l/?uddg=URL">Title</a>
            out: List[SearchResult] = []
            for m in re.finditer(r'<a[^>]*class=\"result__a\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>', html, flags=re.I | re.S):
                href = m.group(1)
                title_raw = re.sub(r"<.*?>", "", m.group(2))
                url = href
                if "/l/?uddg=" in href:
                    try:
                        u = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
                        url = urllib.parse.unquote(u)
                    except Exception:
                        url = href
                # find nearby snippet
                # crude: search next <a class="result__snippet"> ... </a> or <a>??? not robust, but ok for fallback
                snip = ""
                out.append(SearchResult(url=url, title=title_raw.strip(), snippet=snip, source="duckduckgo"))
                if len(out) >= top_k:
                    break
            return out
        except Exception:
            return []


def make_provider(name: Optional[str]) -> BaseSearchProvider:
        key = (name or "mock").lower()
        if key in ("mock", "fallback"):
            return MockSearchProvider()
        if key in ("ddg", "duckduckgo"):
            return DuckduckgoSearchProvider()
        # default mock
        return MockSearchProvider()


def search(query: str, recency_days: int = 14, top_k: int = 8, provider: Optional[str] = None) -> List[SearchResult]:
    p = make_provider(provider)
    res = p.search(query, recency_days=recency_days, top_k=top_k)
    if not res and (provider is None or provider.lower() != "mock"):
        # fallback
        res = MockSearchProvider().search(query, recency_days=recency_days, top_k=top_k)
    return res

