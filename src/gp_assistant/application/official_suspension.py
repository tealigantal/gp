from __future__ import annotations

"""Bounded, read-only official suspension facts for market-run coverage.

This is deliberately not a Serenity task: it has no Top-30 target, batch,
weight, Serenity store, or selection output.  It consumes only the generic
official-announcement transport and exchange verifier, then returns a narrow
fact that the market-run ledger may audit and use to remove a proven no-bar
symbol from one exact-date coverage denominator.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import re
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from ..serenity.parser import extract_pdf_text
from ..serenity.sources import CNInfoClient, ExchangeVerifier
from ..serenity.text import normalize_cn_text


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_TITLE_SUSPENSION = re.compile(r"停牌")


def _published_before_open(value: object, *, trade_date: date) -> str | None:
    """Return a normalized timestamp only when it was knowable before opening."""
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=_SHANGHAI)
    else:
        published = published.astimezone(_SHANGHAI)
    opening = datetime.combine(trade_date, time(9, 30), tzinfo=_SHANGHAI)
    return published.isoformat() if published <= opening else None


def _halt_excerpt(text: str, *, trade_date: date) -> str | None:
    """Require an exact target-date open suspension, never infer it from timing."""
    normalized = re.sub(r"\s+", "", normalize_cn_text(text))
    target = f"{trade_date.year}年{trade_date.month}月{trade_date.day}日"
    token = re.escape(target)
    halt = re.compile(token + r".{0,32}?(?:开市|开盘).{0,32}?(?:继续)?停牌")
    resume = re.compile(token + r".{0,32}?(?:开市|开盘).{0,32}?(?:复牌|恢复交易)")
    match = halt.search(normalized)
    # An earlier notice can say the stock was expected to resume on the target
    # date and the current notice can then explicitly extend the halt.  Only a
    # later same-date resume statement can override the matched halt fact.
    if match is None or resume.search(normalized, match.end()):
        return None
    start = max(0, match.start() - 72)
    end = min(len(normalized), match.end() + 144)
    return normalized[start:end]


@dataclass(frozen=True)
class OfficialSuspensionEvidence:
    symbol: str
    trade_date: str
    source: str
    source_record_id: str
    source_url: str
    published_at: str
    content_digest: str
    verification_basis: str
    verified_at: str
    excerpt: str

    def payload(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "trade_date": self.trade_date,
            "state": "verified_suspended",
            "source": self.source,
            "source_record_id": self.source_record_id,
            "source_url": self.source_url,
            "published_at": self.published_at,
            "effective_suspension_date": self.trade_date,
            "content_digest": self.content_digest,
            "verification_basis": self.verification_basis,
            "verified_at": self.verified_at,
            "excerpt": self.excerpt,
        }


class OfficialSuspensionEvidenceCollector:
    """Resolve a small set of still-missing bars to verified no-bar facts.

    Network or parse ambiguity is intentionally represented as no fact.  The
    caller therefore keeps the symbol missing and retries normal daily data.
    """

    def __init__(
        self,
        *,
        client: CNInfoClient | None = None,
        verifier: ExchangeVerifier | None = None,
        parser: Callable[..., tuple[str, str]] = extract_pdf_text,
        timeout_sec: float = 15.0,
        page_size: int = 30,
        page_budget: int = 10,
        spacing_sec: float = 1.0,
        pdf_max_bytes: int = 15 * 1024 * 1024,
    ) -> None:
        self.client = client or CNInfoClient(
            timeout_sec=timeout_sec,
            page_size=page_size,
            page_budget=page_budget,
            spacing_sec=spacing_sec,
        )
        self.verifier = verifier or ExchangeVerifier(timeout_sec=timeout_sec)
        self.parser = parser
        self.pdf_max_bytes = max(1, int(pdf_max_bytes))

    def resolve(
        self,
        *,
        symbols: tuple[str, ...],
        trade_date: date,
        observed_at: datetime,
    ) -> dict[str, dict[str, object]]:
        wanted = tuple(sorted({str(symbol).zfill(6) for symbol in symbols}))
        if not wanted:
            return {}
        try:
            stock_map = self.client.load_stock_map()
        except Exception:  # Official discovery is fail-closed and non-blocking.
            return {}
        start = trade_date - timedelta(days=10)
        output: dict[str, dict[str, object]] = {}
        for symbol in wanted:
            stock = stock_map.get(symbol)
            if not isinstance(stock, Mapping) or not str(stock.get("org_id") or ""):
                continue
            try:
                page = self.client.fetch_symbol(symbol, str(stock["org_id"]), start=start, end=trade_date)
            except Exception:
                continue
            if not bool(page.get("complete")) or bool(page.get("backlog")):
                continue
            for record in page.get("records") or []:
                if not isinstance(record, Mapping) or str(record.get("symbol") or "") != symbol:
                    continue
                if not _TITLE_SUSPENSION.search(str(record.get("title") or "")):
                    continue
                published_at = _published_before_open(record.get("published_at"), trade_date=trade_date)
                if published_at is None:
                    continue
                try:
                    if not self.verifier.verify(dict(record), start=start, end=trade_date):
                        continue
                    document = self.client.download_pdf(str(record["source_url"]), max_bytes=self.pdf_max_bytes)
                    text, parse_state = self.parser(document, max_pages=40, max_chars=250_000, timeout_sec=20.0)
                except Exception:
                    continue
                if parse_state != "parsed":
                    continue
                excerpt = _halt_excerpt(text, trade_date=trade_date)
                if excerpt is None:
                    continue
                evidence = OfficialSuspensionEvidence(
                    symbol=symbol,
                    trade_date=trade_date.isoformat(),
                    source="cninfo+szse" if not symbol.startswith("6") else "cninfo+sse",
                    source_record_id=str(record.get("source_record_id") or ""),
                    source_url=str(record.get("source_url") or ""),
                    published_at=published_at,
                    content_digest=sha256(document).hexdigest(),
                    verification_basis="szse_announcement_id" if not symbol.startswith("6") else "sse_symbol_title",
                    verified_at=observed_at.astimezone(_SHANGHAI).isoformat() if observed_at.tzinfo else observed_at.replace(tzinfo=_SHANGHAI).isoformat(),
                    excerpt=excerpt,
                )
                output[symbol] = evidence.payload()
                break
        return output
