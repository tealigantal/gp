from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

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
    # Try readability-lxml
    try:
        from readability import Document  # type: ignore
        doc = Document(html)
        title = doc.short_title()
        content_html = doc.summary()
        # strip tags quickly
        import re
        text = re.sub(r'<[^>]+>', ' ', content_html)
        text = ' '.join(text.split())
        return text
    except Exception:
        # Minimal fallback: plain tag strip (still real content fetch)
        import re
        text = re.sub(r'<[^>]+>', ' ', html)
        text = ' '.join(text.split())
        # keep it possibly long so LLM has signal
        return text[:4000]


class MarketInfo:
    def __init__(self, repo_root: Path, *, llm_cfg_path: str, search_cfg_path: str) -> None:
        self.repo_root = Path(repo_root)
        self.llm = LLMClient(llm_cfg_path)  # fail-fast if misconfigured
        self.search = SearchClient(search_cfg_path)  # fail-fast

    def run(self, run_dir: Path, *, end_date: str, lookback_days: int, queries: List[str]) -> Tuple[MarketContext, List[MarketSource]]:
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        start_dt = end_dt - timedelta(days=lookback_days)
        start_s, end_s = _yyyymmdd(start_dt), _yyyymmdd(end_dt)

        # Search and fetch articles
        results = []
        for q in queries:
            results.extend(self.search.search(q, recency_days=lookback_days, top_k=8))
        # Dedup by URL
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
        # Save sources JSONL
        save_jsonl(run_dir / '01_sources.jsonl', rows)

        # LLM summarization
        sys_prompt = (
            '你是投研分析助手。根据给定的新闻与市场材料，严格输出 JSON（不得多余文本），字段：\n'
            'provider, date_range{start,end}, index_summary, sector_rotation[], major_events[], market_style_guess{style,reason}, risk_flags[], sources[].\n'
            'sources 要包含原始 url/title/snippet/published_at/抓取时间 和每条的 evidence 概要。\n'
            '尽量估算主要指数区间涨跌与量能变化（如缺数据可从上下文描述中提取近似）。'
        )
        user_payload = {
            'date_range': {'start': start_s, 'end': end_s},
            'articles': [s.dict() for s in sources],
            'schema_hint': {
                'provider': 'web_search',
                'index_summary': {'hs300': {'return': 'approx%'}},
            }
        }
        save_prompt(run_dir, '01', 'market_info', {'model': self.llm.cfg.model, 'provider': self.llm.cfg.provider, 'messages': [{'role':'system','content':sys_prompt}, {'role':'user','content':user_payload}]})
        resp = self.llm.chat([
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': __import__('json').dumps(user_payload, ensure_ascii=False)},
        ], json_response=True)
        save_llm_raw(run_dir, '01', 'market_info', resp)
        txt = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
        data = __import__('json').loads(txt)
        ctx = MarketContext(**data)
        save_json(run_dir / '01_market_context.json', ctx.dict())
        return ctx, sources

