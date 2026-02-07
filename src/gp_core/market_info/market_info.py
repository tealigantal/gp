from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

import requests

from gp_core.io import save_json, save_jsonl, save_prompt, save_llm_raw
from gp_core.llm import LLMClient
from gp_core.schemas import MarketContext, MarketSource
from gp_core.search import SearchClient


def _iso_now() -> str:
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


def _yyyymmdd(d: datetime) -> str:
    return d.strftime('%Y%m%d')


def fetch_url(url: str) -> str:
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    html = r.text
    try:
        from readability import Document  # type: ignore
        doc = Document(html)
        content_html = doc.summary()
        import re
        text = re.sub(r'<[^>]+>', ' ', content_html)
        return ' '.join(text.split())
    except Exception:
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        return ' '.join(text.split())[:4000]


class MarketInfo:
    def __init__(self, repo_root: Path, *, llm_cfg_path: str, search_cfg_path: str) -> None:
        self.repo_root = Path(repo_root)
        self.llm = LLMClient(llm_cfg_path)
        self.search = SearchClient(search_cfg_path)

    def run(self, run_dir: Path, *, end_date: str, lookback_days: int, queries: List[str]) -> Tuple[MarketContext, List[MarketSource]]:
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        start_dt = end_dt - timedelta(days=lookback_days)
        start_s, end_s = _yyyymmdd(start_dt), _yyyymmdd(end_dt)

        results = []
        for q in queries:
            results.extend(self.search.search(q, recency_days=lookback_days, top_k=8))
        seen = set()
        hits = []
        for r in results:
            if r.url and r.url not in seen:
                seen.add(r.url)
                hits.append(r)
        sources: List[MarketSource] = []
        rows = []
        for h in hits:
            try:
                body = fetch_url(h.url)
            except Exception:
                body = ''
            src = MarketSource(provider='web', url=h.url, title=h.title, snippet=h.snippet, fetched_at=_iso_now(), published_at=h.published_at, article_summary=body[:800])
            sources.append(src)
            rows.append(src.dict())
        save_jsonl(run_dir / '01_sources.jsonl', rows)

        sys_prompt = (
            '你是投研分析助手。只返回 JSON，不要多余文字。字段：'
            'provider, date_range{start,end}, index_summary, sector_rotation[], major_events[], '
            'market_style_guess{style,reason}, risk_flags[], sources[]。'
            'sources 每项包含 url/title/snippet/published_at/fetched_at 与简要证据摘要。请使用简体中文。'
        )
        content = {
            'date_range': {'start': start_s, 'end': end_s},
            'articles': [s.dict() for s in sources],
            'schema_hint': {'provider': 'web_search'},
        }
        save_prompt(run_dir, '01', 'market_info', {
            'model': self.llm.cfg.model,
            'provider': self.llm.cfg.provider,
            'messages': [{'role':'system','content':sys_prompt}, {'role':'user','content':content}],
        })
        resp = self.llm.chat([
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': __import__('json').dumps(content, ensure_ascii=False)},
        ], json_response=True)
        save_llm_raw(run_dir, '01', 'market_info', resp)
        txt = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
        data = __import__('json').loads(txt)
        ctx = MarketContext(**data)
        save_json(run_dir / '01_market_context.json', ctx.dict())
        return ctx, sources
