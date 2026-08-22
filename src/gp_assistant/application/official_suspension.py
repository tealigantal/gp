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


def _date_token(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def _positive_resume_exists(normalized: str, *, trade_date: date, start: int = 0) -> bool:
    """Reject a real target-date resume, but not a statement that it cannot resume."""
    token = re.escape(_date_token(trade_date))
    pattern = re.compile(token + r".{0,48}?(?:开市|开盘).{0,32}?(?:复牌|恢复交易)")
    for match in pattern.finditer(normalized, start):
        context = normalized[max(start, match.start() - 48):match.start()]
        if re.search(r"(?:无法|未能|不能|不得|不(?:会|得|再)?在)", context):
            continue
        return True
    return False


def _halt_evidence(text: str, *, trade_date: date) -> tuple[str, str] | None:
    """Return an auditable exact-date or bounded-continuation halt fact.

    A missing bar remains retryable unless the parsed official document binds
    the target date directly, explicitly continues an earlier halt, or gives a
    short declared halt window that still contains the target date.  The
    latter is accepted only together with identity/exchange verification and
    a complete pre-open announcement; it is never inferred from provider
    emptiness alone.
    """
    normalized = re.sub(r"\s+", "", normalize_cn_text(text))
    target = _date_token(trade_date)
    token = re.escape(target)
    exact_patterns = (
        re.compile(token + r".{0,32}?(?:开市|开盘).{0,32}?(?:继续)?停牌"),
        # One-day risk-warning suspensions use an explicit "停牌日期" field or
        # state that the stock "will halt for one day" without the words
        # 开市/开盘.  Both still bind the exact target date and do not infer a
        # halt merely from a missing daily bar.
        re.compile(r"停牌日期(?:为|：|:)?" + token),
        re.compile(r"(?:公司)?股票(?:将)?于" + token + r"停牌(?:1天|一天|全天)"),
    )
    matches = [match for pattern in exact_patterns if (match := pattern.search(normalized)) is not None]
    match = min(matches, key=lambda item: item.start()) if matches else None
    if match is not None and not _positive_resume_exists(normalized, trade_date=trade_date, start=match.end()):
        start = max(0, match.start() - 72)
        end = min(len(normalized), match.end() + 144)
        return normalized[start:end], "exact_target_date"

    # Multi-day notices commonly say "自 8 月 19 日开市起继续停牌" while the
    # target session is 8 月 20 日.  Bind the start date and require explicit
    # continuation language; do not carry a bare missing-bar result forward.
    date_pattern = re.compile(
        r"自(?P<year>20\d{2})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日.{0,40}?(?:开市|开盘).{0,40}?(?:开始)?停牌"
    )
    for candidate in date_pattern.finditer(normalized):
        started = date(int(candidate.group("year")), int(candidate.group("month")), int(candidate.group("day")))
        if started > trade_date:
            continue
        window = normalized[max(0, candidate.start() - 80):min(len(normalized), candidate.end() + 180)]
        if "继续停牌" not in window and "仍停牌" not in window and "停牌" not in window:
            continue
        if _positive_resume_exists(normalized, trade_date=trade_date, start=candidate.end()):
            continue
        # A declared maximum window is accepted only when it is short and the
        # target remains inside it.  It is an auditable bounded continuation,
        # not a prediction of future suspension.
        max_match = re.search(r"不超过\s*(?P<days>\d{1,2})\s*个交易日", normalized)
        continuation = "继续停牌" in normalized or "仍停牌" in normalized
        if max_match is None and not continuation:
            continue
        if max_match is not None and not continuation and not re.search(r"停牌(?:期间|期限).{0,120}(?:申请复牌|复牌)", normalized):
            continue
        max_days = int(max_match.group("days")) if max_match else 5
        if max_days > 10 or (trade_date - started).days > max_days:
            continue
        start = max(0, candidate.start() - 72)
        end = min(len(normalized), candidate.end() + 180)
        return normalized[start:end], "continuation_halt"
    return None


def _halt_excerpt(text: str, *, trade_date: date) -> str | None:
    """Compatibility wrapper returning only the audited text excerpt."""
    evidence = _halt_evidence(text, trade_date=trade_date)
    return evidence[0] if evidence else None


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
    evidence_kind: str = "exact_target_date"

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
            "evidence_kind": self.evidence_kind,
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
                halt_evidence = _halt_evidence(text, trade_date=trade_date)
                if halt_evidence is None:
                    continue
                excerpt, evidence_kind = halt_evidence
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
                    evidence_kind=evidence_kind,
                )
                output[symbol] = evidence.payload()
                break
        return output
