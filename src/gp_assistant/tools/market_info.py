from __future__ import annotations

from typing import Any, List, Dict, Tuple

import re
import requests
from bs4 import BeautifulSoup
try:
    from readability import Document
except Exception:  # noqa: BLE001
    Document = None  # type: ignore

from ..core.types import ToolResult


def _fetch_list(url: str, selectors: List[str], limit: int = 20) -> List[Dict[str, str]]:
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        html = r.text
        soup = BeautifulSoup(html, "lxml")
        links = []
        for sel in selectors:
            for a in soup.select(sel):
                title = (a.get_text() or "").strip()
                href = a.get("href") or ""
                if not title or len(title) < 6:
                    continue
                if href and href.startswith("/"):
                    # best-effort absolute url
                    from urllib.parse import urljoin

                    href = urljoin(url, href)
                links.append({"title": title, "url": href or url})
        # de-duplicate by title
        seen = set()
        items: List[Dict[str, str]] = []
        for it in links:
            if it["title"] in seen:
                continue
            seen.add(it["title"])
            items.append(it)
        return items[:limit]
    except Exception:
        return []


def _summarize_urls(urls: List[str], limit: int = 3) -> Tuple[str, List[Dict[str, str]]]:
    summaries: List[str] = []
    picked: List[Dict[str, str]] = []
    for u in urls[:limit]:
        try:
            rr = requests.get(u, timeout=10)
            rr.raise_for_status()
            if Document is not None:
                doc = Document(rr.text)
                text = BeautifulSoup(doc.summary(), "lxml").get_text("\n", strip=True)
                title = doc.short_title()
            else:
                soup = BeautifulSoup(rr.text, "lxml")
                # remove script/style
                for tag in soup(["script", "style"]):
                    tag.decompose()
                text = soup.get_text("\n", strip=True)
                title = soup.title.get_text(strip=True) if soup.title else ""
            # Take first ~200 chars as gist
            gist = re.sub(r"\s+", " ", text)[:200]
            if gist:
                summaries.append(gist)
                picked.append({"title": title, "url": u})
        except Exception:
            continue
    if summaries:
        return " / ".join(summaries), picked
    return "", []


def run_market_info(args: dict, state: Any) -> ToolResult:  # noqa: ANN401
    date = args.get("date")
    # 多源抓取（无 Key）：优先东方财富，其次新浪财经，尽量提取标题与若干篇正文摘要
    sources: List[Dict[str, str]] = []
    # 东方财富：股票要闻/首页列表（选择尽可能稳定的选择器 + 退化为通用 a[href]）
    sources.extend(
        _fetch_list(
            "https://stock.eastmoney.com/",
            selectors=["a[title]", "#newsList a", ".newsList a", "a[href*='/a/']"],
            limit=20,
        )
    )
    if not sources:
        sources.extend(
            _fetch_list("https://finance.eastmoney.com/", selectors=["a[title]", "a[href*='/a/']"], limit=20)
        )
    if not sources:
        # 新浪财经 7x24
        sources.extend(_fetch_list("https://finance.sina.com.cn/7x24/", selectors=["a[href]"], limit=20))

    titles = [s["title"] for s in sources]
    urls = [s["url"] for s in sources if s.get("url")]
    short, picked = _summarize_urls(urls, limit=3)
    summary = short or ("；".join(titles[:6]) if titles else "未获取到新闻")
    # 将更可靠的已摘取正文的条目置顶
    ordered = picked + [s for s in sources if s.get("url") not in {p["url"] for p in picked}]
    return ToolResult(ok=True, message="已抓取市场资讯", data={"date": date, "summary": summary, "sources": ordered[:20]})
