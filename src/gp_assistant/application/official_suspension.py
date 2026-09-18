from __future__ import annotations

"""Official no-bar evidence: discovery -> document facts -> dated resolution.

Independent of Serenity targets/scoring/storage. Only the market-run worker
may turn a verified result into an audited exact-date coverage exclusion.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from hashlib import sha256
import re
from typing import Callable, Mapping
from zoneinfo import ZoneInfo

from ..serenity.parser import extract_pdf_text
from ..serenity.sources import CNInfoClient, ExchangeVerifier
from .suspension_facts import (
    MAX_HALT_SESSIONS, POLICY_REVISION, TradingStatusFact,
    disclosure_role, parse_status_facts,
)
from .trading_calendar import CnATradingCalendar, load_cn_a_calendar


_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _published_before_open(value: object, *, trade_date: date) -> str | None:
    try:
        published = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    published = published.replace(tzinfo=_SHANGHAI) if published.tzinfo is None else published.astimezone(_SHANGHAI)
    opening = datetime.combine(trade_date, time(9, 30), tzinfo=_SHANGHAI)
    return published.isoformat() if published <= opening else None


@dataclass(frozen=True)
class SuspensionResolution:
    evidence_by_symbol: dict[str, dict[str, object]] = field(default_factory=dict)
    diagnostics_by_symbol: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class _Witness:
    fact: TradingStatusFact
    published_at: str
    record: Mapping[str, object]
    digest: str


class OfficialSuspensionEvidenceCollector:
    """Resolve a bounded missing-bar residue without hiding failed evidence.

    Every parsed disclosure participates in conflict checks. Unreadable known
    ancillary reports do not veto a status notice; unknown/status/correction
    documents remain fail-closed. There is no symbol-specific exception list.
    """

    def __init__(
        self, *, client: CNInfoClient | None = None,
        verifier: ExchangeVerifier | None = None,
        parser: Callable[..., tuple[str, str]] = extract_pdf_text,
        calendar: CnATradingCalendar | None = None,
        timeout_sec: float = 15.0, page_size: int = 30, page_budget: int = 10,
        spacing_sec: float = 1.0, pdf_max_bytes: int = 15 * 1024 * 1024,
    ) -> None:
        self.client = client or CNInfoClient(timeout_sec=timeout_sec, page_size=page_size,
                                            page_budget=page_budget, spacing_sec=spacing_sec)
        self.verifier = verifier or ExchangeVerifier(timeout_sec=timeout_sec)
        self.parser = parser
        self.calendar = calendar
        self.pdf_max_bytes = max(1, int(pdf_max_bytes))

    def resolve(self, *, symbols: tuple[str, ...], trade_date: date,
                observed_at: datetime) -> SuspensionResolution:
        wanted = tuple(sorted({str(symbol).zfill(6) for symbol in symbols}))
        checked_at = (observed_at.replace(tzinfo=_SHANGHAI) if observed_at.tzinfo is None
                      else observed_at.astimezone(_SHANGHAI)).isoformat()
        diagnostics: dict[str, dict[str, object]] = {
            symbol: {"symbol": symbol, "trade_date": trade_date.isoformat(), "checked_at": checked_at,
                     "policy_revision": POLICY_REVISION, "state": "unresolved", "documents": []}
            for symbol in wanted
        }
        result = SuspensionResolution(diagnostics_by_symbol=diagnostics)
        if not wanted:
            return result

        def fail_all(reason: str, exc: Exception | None = None) -> SuspensionResolution:
            for diagnostic in diagnostics.values():
                diagnostic["reason"] = reason
                if exc:
                    diagnostic["error"] = f"{type(exc).__name__}:{exc}"[:500]
            return result

        try:
            calendar = self.calendar or load_cn_a_calendar()
            if not calendar.is_open(trade_date):
                return fail_all("target_not_open")
            # Ten supported sessions plus their preceding publication session;
            # weekends/holidays must not truncate discovery or duration checks.
            start = trade_date
            for _ in range(MAX_HALT_SESSIONS):
                start = calendar.previous_open_before(start)
        except Exception as exc:
            return fail_all("calendar_unavailable", exc)
        for diagnostic in diagnostics.values():
            diagnostic.update({"disclosure_start": start.isoformat(), "calendar": calendar.ref.model_dump(mode="json")})
        try:
            stock_map = self.client.load_stock_map()
        except Exception as exc:
            return fail_all("discovery_failed", exc)
        for symbol in wanted:
            diagnostic = diagnostics[symbol]
            stock = stock_map.get(symbol)
            if not isinstance(stock, Mapping) or not str(stock.get("org_id") or ""):
                diagnostic["reason"] = "issuer_identity_missing"
                continue
            try:
                page = self.client.fetch_symbol(symbol, str(stock["org_id"]), start=start, end=trade_date)
            except Exception as exc:
                diagnostic.update({"reason": "discovery_failed", "error": f"{type(exc).__name__}:{exc}"[:500]})
                continue
            if not bool(page.get("complete")) or bool(page.get("backlog")):
                diagnostic["reason"] = "discovery_incomplete"
                continue
            halts: list[_Witness] = []
            resumes: list[_Witness] = []
            unknown: list[str | None] = []
            disclosures: list[tuple[str, Mapping[str, object], str]] = []
            documents: list[dict[str, object]] = []
            diagnostic["documents"] = documents
            for record in page.get("records") or []:
                if not isinstance(record, Mapping) or str(record.get("symbol") or "") != symbol:
                    documents.append({"reason": "issuer_mismatch", "blocking": True})
                    unknown.append(None)
                    continue
                doc: dict[str, object] = {"source_record_id": record.get("source_record_id"),
                                          "title": record.get("title"), "published_at": record.get("published_at")}
                documents.append(doc)
                published_at = _published_before_open(record.get("published_at"), trade_date=trade_date)
                if published_at is None:
                    # Future documents cannot influence an as-of decision, but
                    # malformed timestamps cannot silently imply irrelevance.
                    try:
                        datetime.fromisoformat(str(record.get("published_at")).replace("Z", "+00:00"))
                    except ValueError:
                        doc.update({"reason": "invalid_publication_date", "blocking": True})
                        unknown.append(None)
                    else:
                        doc.update({"reason": "after_target_open", "blocking": False})
                    continue
                role = disclosure_role(str(record.get("title") or ""))
                doc["document_role"] = role
                blocking = role != "ancillary_document"
                disclosure_index = len(disclosures)
                disclosures.append((published_at, record, ""))

                def reject(reason: str, exc: Exception | None = None) -> None:
                    doc.update({"reason": reason, "blocking": blocking})
                    if exc:
                        doc["error"] = f"{type(exc).__name__}:{exc}"[:500]
                    if blocking:
                        unknown.append(published_at)

                if not record.get("source_record_id") or not str(record.get("source_url") or "").startswith("https://"):
                    reject("document_identity_missing")
                    continue
                try:
                    if not self.verifier.verify(dict(record), start=start, end=trade_date, raise_on_error=True):
                        reject("exchange_unverified")
                        continue
                except Exception as exc:
                    reject("exchange_failed", exc)
                    continue
                try:
                    document = self.client.download_pdf(str(record["source_url"]), max_bytes=self.pdf_max_bytes)
                    doc["content_digest"] = sha256(document).hexdigest()
                    text, parse_state = self.parser(document, max_pages=40, max_chars=250_000, timeout_sec=20.0)
                except Exception as exc:
                    reject("document_failed", exc)
                    continue
                if parse_state != "parsed":
                    reject(f"parse_{parse_state}")
                    continue
                disclosures[disclosure_index] = (published_at, record, text)
                try:
                    facts = parse_status_facts(text)
                    evaluated = [(fact, fact.validity(trade_date, calendar)) for fact in facts]
                except ValueError as exc:
                    # Parsed malformed status assertions are relevant even in
                    # an otherwise ancillary report.
                    blocking = True
                    reject("invalid_status_fact", exc)
                    continue
                doc["facts"] = [dict(fact.payload(), validity=validity) for fact, validity in evaluated]
                if not facts and re.search(r"停牌|复牌|恢复交易", str(record.get("title") or "")):
                    reject("status_notice_unresolved")
                    continue
                doc.update({"reason": "evaluated", "blocking": False})
                for fact, validity in evaluated:
                    if validity != "effective":
                        continue
                    witness = _Witness(fact, published_at, record, str(doc["content_digest"]))
                    (halts if fact.state == "halted" else resumes).append(witness)
            if not halts:
                diagnostic["reason"] = "no_effective_halt"
                continue
            latest = max(halts, key=lambda item: (item.published_at, item.fact.starts_on))
            if any(stamp is None or stamp >= latest.published_at for stamp in unknown):
                diagnostic["reason"] = "unresolved_status_disclosure"
                continue
            triggers = [str(record.get("source_record_id") or "unknown") for stamp, record, text in disclosures
                        if stamp >= latest.published_at
                        and record.get("source_record_id") != latest.record["source_record_id"]
                        and latest.fact.may_fulfil_resumption(title=str(record.get("title") or ""), text=text)]
            if triggers:
                diagnostic.update({"reason": "resumption_condition_may_be_fulfilled", "conflicting_record_ids": triggers})
                continue
            # Effective chronology matters: an old resume cannot cancel a new
            # later suspension, nor can a restatement erase an effective resume.
            if any(item.fact.starts_on >= latest.fact.starts_on for item in resumes):
                diagnostic["reason"] = "effective_resumption_conflict"
                continue
            fact = latest.fact
            evidence = {
                "symbol": symbol, "trade_date": trade_date.isoformat(), "state": "verified_suspended",
                "source": "cninfo+sse" if symbol.startswith("6") else "cninfo+szse",
                "source_record_id": latest.record["source_record_id"], "source_url": latest.record["source_url"],
                "published_at": latest.published_at, "effective_suspension_date": trade_date.isoformat(),
                "content_digest": latest.digest,
                "verification_basis": "sse_symbol_title" if symbol.startswith("6") else "szse_announcement_id",
                "verified_at": checked_at, "excerpt": fact.excerpt,
                "evidence_kind": "exact_target_date" if fact.starts_on == trade_date else fact.kind,
                "policy_revision": POLICY_REVISION, "status_fact": fact.payload(),
                "elapsed_sessions": len(calendar.open_days_between(fact.starts_on, trade_date)),
                "calendar": calendar.ref.model_dump(mode="json"),
            }
            diagnostic.update({"state": "verified_suspended", "reason": "verified_halt", "selected_record_id": latest.record["source_record_id"]})
            evidence["suspension_check"] = diagnostic
            result.evidence_by_symbol[symbol] = evidence
        return result
