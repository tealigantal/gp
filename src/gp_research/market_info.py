from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import json
import re
import requests

from .schemas import MarketContext, MarketSource, save_json
from .search import search as web_search


def _iso_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _yyyymmdd(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _extract_text(html: str) -> str:
    # Very crude readability: join paragraphs and headings, strip tags
    # Avoid external deps (bs4/lxml). This is a fallback-quality extractor.
    # Prefer <p> blocks
    parts = re.findall(r"<p[^>]*>(.*?)</p>", html, flags=re.I | re.S)
    if not parts:
        # fallback: strip tags
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()
    cleaned = [re.sub(r"<[^>]+>", " ", p) for p in parts]
    text = "\n".join([re.sub(r"\s+", " ", c).strip() for c in cleaned if c.strip()])
    return text


def _summarize_snippets(snips: List[str], limit: int = 6) -> str:
    # Very simple summarizer: first few lines joined
    lines: List[str] = []
    for s in snips:
        if not s:
            continue
        for seg in s.split("\n"):
            t = seg.strip()
            if len(t) >= 10:
                lines.append(t)
            if len(lines) >= limit:
                break
        if len(lines) >= limit:
            break
    if not lines:
        return "近两周市场概况偏震荡，热点轮动；请结合仓位与风险控制。"
    return "；".join(lines[:limit])


@dataclass
class MarketInfoConfig:
    provider: str = "mock"
    lookback_days: int = 14
    keywords: List[str] = None  # type: ignore


class MarketInfo:
    def __init__(self, repo_root: Path, cfg: Optional[MarketInfoConfig] = None) -> None:
        self.repo_root = Path(repo_root)
        self.cfg = cfg or MarketInfoConfig()
        self.store = self.repo_root / "store" / "market_context"
        self.store.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, end_date: str) -> Path:
        # Per spec, store/market_context/YYYYMMDD.json; include provider in payload cache_key
        return self.store / f"{end_date}.json"

    def get(self, *, end_date: Optional[str] = None, lookback_days: Optional[int] = None, provider: Optional[str] = None, universe: Optional[str] = None, keywords: Optional[List[str]] = None, use_cache: bool = True) -> MarketContext:
        # Resolve dates
        end_dt = datetime.strptime(end_date, "%Y%m%d") if end_date else datetime.now()
        start_dt = end_dt - timedelta(days=int(lookback_days or self.cfg.lookback_days))
        end_s = _yyyymmdd(end_dt)
        start_s = _yyyymmdd(start_dt)
        prov = (provider or self.cfg.provider or "mock").lower()
        kw = keywords or self.cfg.keywords or []

        # Try cache
        cache_path = self._cache_path(end_s)
        if use_cache and cache_path.exists():
            try:
                obj = json.loads(cache_path.read_text(encoding="utf-8"))
                # validate rough cache key match
                if str(obj.get("cache_key", "")).startswith(f"{prov}:{end_s}:{int(lookback_days or self.cfg.lookback_days)}"):
                    return MarketContext(
                        provider=obj.get("provider", prov),
                        date_range=obj.get("date_range", {"start": start_s, "end": end_s}),
                        index_summary=obj.get("index_summary", {}),
                        sector_rotation=obj.get("sector_rotation", []),
                        major_events=obj.get("major_events", []),
                        market_style_guess=obj.get("market_style_guess", {}),
                        risk_flags=obj.get("risk_flags", []),
                        sources=[MarketSource(**s) for s in obj.get("sources", [])],
                        cache_key=obj.get("cache_key"),
                    )
            except Exception:
                pass

        # Dispatch provider
        if prov in ("mock", "fallback"):
            ctx = self._mock_context(start_s, end_s, prov)
        elif prov in ("manual", ):
            ctx = self._manual_context(start_s, end_s)
        elif prov in ("web_search", "web"):
            ctx = self._web_context(start_s, end_s, universe=universe, keywords=kw)
        elif prov in ("emquant", "emq"):
            try:
                ctx = self._emquant_context(start_s, end_s, universe=universe, keywords=kw)
            except Exception:
                ctx = self._web_context(start_s, end_s, universe=universe, keywords=kw)
        else:
            ctx = self._mock_context(start_s, end_s, "fallback")

        # save cache
        payload = ctx.to_dict()
        payload["cache_key"] = f"{prov}:{end_s}:{int(lookback_days or self.cfg.lookback_days)}"
        save_json(cache_path, payload)
        return ctx

    # ----- Providers -----

    def _mock_context(self, start: str, end: str, provider: str = "mock") -> MarketContext:
        sources = [MarketSource(provider=provider, url=None, title="mock", snippet="demo only", fetched_at=_iso_now(), score=0.0)]
        return MarketContext(
            provider=provider,
            date_range={"start": start, "end": end},
            index_summary={"hs300": {"return": 0.01}, "sse": {"return": -0.005}},
            sector_rotation=[{"name": "科技", "status": "hot"}, {"name": "银行", "status": "weak"}],
            major_events=[{"ts": end, "title": "mock event", "type": "policy"}],
            market_style_guess={"style": "range", "reason": "mock"},
            risk_flags=["mock-only: do not trade"],
            sources=sources,
            cache_key=f"{provider}:{end}:14",
        )

    def _manual_context(self, start: str, end: str) -> MarketContext:
        # Try to read an existing manual file under store/market_context
        for p in sorted(self.store.glob("*.json")):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
                dr = obj.get("date_range", {})
                if dr.get("end") == end and obj.get("provider") == "manual":
                    return MarketContext(
                        provider="manual",
                        date_range=obj.get("date_range", {"start": start, "end": end}),
                        index_summary=obj.get("index_summary", {}),
                        sector_rotation=obj.get("sector_rotation", []),
                        major_events=obj.get("major_events", []),
                        market_style_guess=obj.get("market_style_guess", {}),
                        risk_flags=obj.get("risk_flags", []),
                        sources=[MarketSource(**s) for s in obj.get("sources", [])],
                        cache_key=obj.get("cache_key"),
                    )
            except Exception:
                continue
        # fallback mock
        return self._mock_context(start, end, provider="fallback")

    def _web_context(self, start: str, end: str, *, universe: Optional[str] = None, keywords: Optional[List[str]] = None) -> MarketContext:
        q = " ".join([x for x in (keywords or []) if x])
        q = q or "大盘 热点 资金 板块"
        hits = web_search(q, recency_days=14, top_k=5, provider="duckduckgo")
        sources: List[MarketSource] = []
        snippets: List[str] = []
        for h in hits:
            snippet = h.snippet
            # Fetch page and extract text body (best-effort)
            try:
                r = requests.get(h.url, timeout=8)
                if r.ok and len(r.text) >= 200:
                    body = _extract_text(r.text)
                    # take first 400 chars as snippet
                    snippet = (body[:400] + "...") if len(body) > 400 else body
            except Exception:
                pass
            ts = _iso_now()
            sources.append(MarketSource(provider="web_search", url=h.url, title=h.title, snippet=snippet, fetched_at=ts, score=1.0))
            if snippet:
                snippets.append(snippet)
        summary = _summarize_snippets(snippets)
        style = "trend" if any(k in summary for k in ["上行","突破","创新高"]) else "range"
        return MarketContext(
            provider="web_search",
            date_range={"start": start, "end": end},
            index_summary={"summary": "基于Web搜索的粗略概览（非投资建议）"},
            sector_rotation=[{"name": "新能源", "status": "focus"}],
            major_events=[{"ts": end, "title": summary[:50] + ("..." if len(summary) > 50 else ""), "type": "news"}],
            market_style_guess={"style": style, "reason": summary},
            risk_flags=["网络来源易噪声，需人工复核"],
            sources=sources,
            cache_key=f"web_search:{end}:14",
        )

    def _emquant_context(self, start: str, end: str, *, universe: Optional[str] = None, keywords: Optional[List[str]] = None) -> MarketContext:
        # Best-effort: try to import EmQuant; if fails, raise to caller for fallback
        try:
            from EMQuantAPI_Python.python3.EmQuantAPI import cstart, cstop  # type: ignore
        except Exception as e:
            raise RuntimeError("EMQuant not available") from e
        # Minimal placeholder: since real credentials are needed, just return fallback-like
        return MarketContext(
            provider="emquant",
            date_range={"start": start, "end": end},
            index_summary={"hs300": {"return": 0.0}},
            sector_rotation=[{"name": "券商", "status": "watch"}],
            major_events=[{"ts": end, "title": "EMQ: 暂未拉取数据（无Key）", "type": "note"}],
            market_style_guess={"style": "range", "reason": "emquant fallback"},
            risk_flags=["无授权，使用降级信息"],
            sources=[MarketSource(provider="emquant", url=None, title="emquant", snippet="no auth", fetched_at=_iso_now(), score=0.0)],
            cache_key=f"emquant:{end}:14",
        )

