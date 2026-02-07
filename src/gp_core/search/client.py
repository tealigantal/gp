from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

import requests
import re
import urllib.parse
import yaml


@dataclass
class SearchConfig:
    provider: str
    api_key_env: str
    default_recency_days: int
    default_top_k: int


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    published_at: Optional[str] = None


def load_search_config(path: str) -> SearchConfig:
    raw = yaml.safe_load(open(path, 'r', encoding='utf-8').read()) or {}
    prov = str(raw.get('provider', '')).lower()
    if not prov:
        prov = 'duckduckgo'
    return SearchConfig(
        provider=prov,
        api_key_env=str(raw.get('api_key_env', '')),
        default_recency_days=int(raw.get('default_recency_days', 14)),
        default_top_k=int(raw.get('default_top_k', 8)),
    )


class SearchClient:
    def __init__(self, cfg_path: str):
        self.cfg = load_search_config(cfg_path)
        api_key = os.getenv(self.cfg.api_key_env) if self.cfg.api_key_env else None
        self.api_key = api_key

    def search(self, query: str, *, recency_days: Optional[int] = None, top_k: Optional[int] = None) -> List[SearchResult]:
        prov = self.cfg.provider
        if prov in ('tavily',):
            return self._tavily(query, recency_days or self.cfg.default_recency_days, top_k or self.cfg.default_top_k)
        elif prov in ('bing',):
            return self._bing(query, top_k or self.cfg.default_top_k)
        elif prov in ('serpapi',):
            return self._serpapi(query, top_k or self.cfg.default_top_k)
        elif prov in ('duckduckgo','ddg','duckduckgo_html'):
            return self._duckduckgo_html(query, top_k or self.cfg.default_top_k)
        raise RuntimeError(f'Unknown search provider: {prov}')

    def _tavily(self, query: str, recency_days: int, top_k: int) -> List[SearchResult]:
        # https://api.tavily.com/search
        url = 'https://api.tavily.com/search'
        payload = {
            'api_key': self.api_key,
            'query': query,
            'search_depth': 'advanced',
            'max_results': top_k,
            'include_answer': False,
            'time_range': 'month',
        }
        r = requests.post(url, json=payload, timeout=20)
        r.raise_for_status()
        data = r.json()
        out: List[SearchResult] = []
        for it in data.get('results', [])[:top_k]:
            out.append(SearchResult(url=it.get('url',''), title=it.get('title',''), snippet=it.get('content',''), published_at=it.get('published_date')))
        return out

    def _bing(self, query: str, top_k: int) -> List[SearchResult]:
        # Bing Web Search v7
        url = 'https://api.bing.microsoft.com/v7.0/search'
        headers = { 'Ocp-Apim-Subscription-Key': self.api_key }
        params = { 'q': query, 'count': top_k }
        r = requests.get(url, headers=headers, params=params, timeout=20)
        r.raise_for_status()
        j = r.json()
        web = j.get('webPages', {}).get('value', [])
        out: List[SearchResult] = []
        for it in web[:top_k]:
            out.append(SearchResult(url=it.get('url',''), title=it.get('name',''), snippet=it.get('snippet','')))
        return out

    def _serpapi(self, query: str, top_k: int) -> List[SearchResult]:
        url = 'https://serpapi.com/search.json'
        params = {'engine': 'google', 'q': query, 'api_key': self.api_key, 'num': top_k}
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        j = r.json()
        out: List[SearchResult] = []
        for it in j.get('organic_results', [])[:top_k]:
            out.append(SearchResult(url=it.get('link',''), title=it.get('title',''), snippet=it.get('snippet','')))
        return out

    def _duckduckgo_html(self, query: str, top_k: int) -> List[SearchResult]:
        """Non‑key, HTML-based DDG search (best effort)."""
        url = 'https://duckduckgo.com/html/'
        params = {'q': query}
        try:
            r = requests.get(url, params=params, timeout=15, headers={'User-Agent':'Mozilla/5.0'})
            r.raise_for_status()
            html = r.text
            out: List[SearchResult] = []
            # <a rel="nofollow" class="result__a" href="/l/?uddg=...">Title</a>
            for m in re.finditer(r'<a[^>]*class=\"result__a\"[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>', html, re.I|re.S):
                href = m.group(1)
                title_raw = re.sub(r'<.*?>','', m.group(2))
                u = href
                if '/l/?uddg=' in href:
                    try:
                        u = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get('uddg',[href])[0]
                        u = urllib.parse.unquote(u)
                    except Exception:
                        u = href
                out.append(SearchResult(url=u, title=title_raw.strip(), snippet='', published_at=None))
                if len(out) >= top_k:
                    break
            return out
        except Exception:
            return []
