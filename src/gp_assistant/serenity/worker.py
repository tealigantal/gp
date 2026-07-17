from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..core.config import load_config
from ..core.logging import logger
from ..runtime.market_clock import compute_market_state
from ..runtime.utils import now_iso
from .parser import build_verified_evidence, extract_pdf_text
from .scheduler import compute_schedule, next_due_at
from .sources import CNInfoClient, ExchangeVerifier, SourceError
from .text import best_document_title
from .store import (
    acquire_worker_lease,
    atomic_write_bytes,
    commit_poll,
    ensure_shadow_ready,
    heartbeat_worker_lease,
    initialize_store,
    latest_complete_bootstrap,
    load_cursor,
    load_source_breaker,
    load_source_progress,
    lookup_document,
    raw_dir,
    recent_poll_durations,
    recent_poll_outcomes,
    recover_operational_suspension_after_complete_poll,
    record_bootstrap_run,
    release_worker_lease,
    status_snapshot,
    set_source_breaker,
    clear_source_breaker,
)
from .targets import load_stable_targets
from .evaluation import process_pending_evaluations


_SCHEMA_CONTRACT_VERSION = "cninfo-announcement-envelope-v2"
_COMPLETE_HYDRATION_STATUSES = {"parsed"}


class _LeaseHeartbeater:
    def __init__(self, owner_id: str, lease_sec: int) -> None:
        self.owner_id = owner_id
        self.interval = max(5.0, float(lease_sec) / 3.0)
        self.stop_event = threading.Event()
        self.lost_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="serenity-lease-heartbeat", daemon=True)

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                if not heartbeat_worker_lease(self.owner_id):
                    self.lost_event.set()
                    return
            except Exception:
                self.lost_event.set()
                return

    def start(self) -> None:
        self.thread.start()

    def assert_owned(self) -> None:
        if self.lost_event.is_set():
            raise RuntimeError("serenity_worker_lease_lost")

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=max(1.0, self.interval + 1.0))


def _record_ids(records: Iterable[Dict[str, Any]]) -> List[str]:
    return [str(record.get("source_record_id") or "") for record in records if str(record.get("source_record_id") or "")]


def _consecutive_counts(history: List[Dict[str, Any]]) -> tuple[int, int]:
    empty = 0
    failed = 0
    for row in history:
        source_success = bool(row.get("complete")) and str(row.get("status") or "") == "success"
        if source_success and int(row.get("item_count") or 0) == 0:
            empty += 1
        else:
            break
    for row in history:
        source_success = bool(row.get("complete")) and str(row.get("status") or "") == "success"
        if not source_success:
            failed += 1
        else:
            break
    return empty, failed


def _next_consecutive_counts(
    history: List[Dict[str, Any]],
    *,
    source_complete: bool,
    item_count: int,
) -> tuple[int, int]:
    """Apply the current poll result to the historical failure/empty streaks."""

    empty, failed = _consecutive_counts(history)
    if source_complete:
        return (empty + 1 if int(item_count) == 0 else 0), 0
    return 0, failed + 1


def _raw_path(record_id: str, content_hash: str, published_at: str | None) -> Path:
    try:
        dt = datetime.fromisoformat(str(published_at or "").replace("Z", "+00:00"))
    except Exception:
        dt = datetime.now(timezone.utc)
    safe_record_id = sha256(str(record_id).encode("utf-8")).hexdigest()[:20]
    return raw_dir() / f"{dt.year:04d}" / f"{dt.month:02d}" / f"{safe_record_id}_{content_hash[:12]}.pdf"


def _explicitly_withdrawn(metadata: Dict[str, Any]) -> bool:
    raw = dict(metadata.get("raw_metadata") or {})
    for key in ("withdrawn", "isWithdrawn", "isDeleted", "deleted"):
        value = raw.get(key)
        if value is True or str(value or "").strip().lower() in {"true", "yes", "withdrawn", "retracted"}:
            return True
    status_text = " ".join(
        str(raw.get(key) or "")
        for key in ("announcementStatus", "statusName", "announcementTypeName")
    )
    return any(token in status_text for token in ("撤回", "作废", "retracted", "withdrawn"))


def _record_payload(
    *,
    metadata: Dict[str, Any],
    first_seen_at: str,
    backfill_only: bool,
    client: CNInfoClient,
    verifier: ExchangeVerifier | None,
    start: date,
    end: date,
    pdf_max_bytes: int,
    content_revalidate_hours: float,
) -> Dict[str, Any]:
    source = "cninfo"
    source_record_id = str(metadata["source_record_id"])
    document_id = "serdoc_" + sha256(f"{source}|{source_record_id}".encode()).hexdigest()[:24]
    known = lookup_document(source, source_record_id)
    effective_backfill_only = bool(backfill_only or (known or {}).get("backfill_only"))
    content_hash = str((known or {}).get("content_hash") or "")
    raw_path_value = (known or {}).get("raw_path")
    extraction_status = str((known or {}).get("extraction_status") or "metadata_only")
    facts: List[Any] = []
    hypotheses: List[Any] = []
    metadata_snapshot = dict(metadata.get("raw_metadata") or {})
    evidence: Dict[str, Any] = {
        "source_verified": False,
        "text_chars": 0,
        "metadata_hash": sha256(
            json.dumps(metadata_snapshot, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest(),
        "metadata": metadata_snapshot,
    }
    supersedes = (known or {}).get("current_version_id")
    last_checked = None
    try:
        last_checked = datetime.fromisoformat(str((known or {}).get("last_content_checked_at") or "").replace("Z", "+00:00"))
        if last_checked.tzinfo is None:
            last_checked = last_checked.replace(tzinfo=timezone.utc)
    except Exception:
        last_checked = None
    revalidate_due = last_checked is None or datetime.now(timezone.utc) >= last_checked + timedelta(hours=content_revalidate_hours)
    needs_hydration = (
        not known
        or extraction_status not in _COMPLETE_HYDRATION_STATUSES
        or not raw_path_value
        or not Path(str(raw_path_value)).exists()
        or revalidate_due
    )
    check: Dict[str, Any] = {}
    version: Dict[str, Any] = {}
    hydration_status = extraction_status
    if needs_hydration:
        try:
            pdf = client.download_pdf(str(metadata.get("source_url") or ""), max_bytes=pdf_max_bytes)
            content_hash = sha256(pdf).hexdigest()
            path = _raw_path(source_record_id, content_hash, metadata.get("published_at"))
            if not path.exists():
                atomic_write_bytes(path, pdf)
            raw_path_value = str(path)
            text, extraction_status = extract_pdf_text(pdf)
            evidence["text_chars"] = len(text)
            resolved_title = best_document_title(metadata.get("title"), text)
            evidence["resolved_title"] = resolved_title
            version_id = "server_" + sha256(f"{document_id}|{content_hash}".encode()).hexdigest()[:24]
            preliminary_facts, _ = build_verified_evidence(
                symbol=str(metadata.get("symbol") or ""),
                title=resolved_title,
                text=text,
                published_at=metadata.get("published_at"),
                effective_available_at=first_seen_at,
                source_document_id=document_id,
                source_version_id=version_id,
                source_url=str(metadata.get("source_url") or ""),
                content_hash=content_hash,
                source_verified=False,
                backfill_only=effective_backfill_only,
            )
            if extraction_status != "parsed":
                preliminary_facts = []
            source_verified = False
            if preliminary_facts and verifier is not None:
                source_verified = verifier.verify(
                    {**metadata, "title": resolved_title},
                    start=start,
                    end=end,
                )
            evidence["source_verified"] = source_verified
            evidence["verification_required"] = bool(preliminary_facts)
            if preliminary_facts:
                facts, hypotheses = build_verified_evidence(
                    symbol=str(metadata.get("symbol") or ""),
                    title=resolved_title,
                    text=text,
                    published_at=metadata.get("published_at"),
                    effective_available_at=first_seen_at,
                    source_document_id=document_id,
                    source_version_id=version_id,
                    source_url=str(metadata.get("source_url") or ""),
                    content_hash=content_hash,
                    source_verified=source_verified,
                    backfill_only=effective_backfill_only,
                )
            checked_at = now_iso()
            hydration_status = extraction_status
            check = {
                "check_id": "sercheck_" + sha256(f"{document_id}|{checked_at}|{content_hash}".encode()).hexdigest()[:24],
                "checked_at": checked_at,
                "content_hash": content_hash,
                "status": extraction_status,
            }
        except SourceError as ex:
            if ex.schema_error or ex.status_code in {401, 403, 429}:
                raise
            hydration_status = f"source_error:{str(ex)[:120]}"
            checked_at = now_iso()
            check = {
                "check_id": "sercheck_"
                + sha256(f"{document_id}|{checked_at}|{hydration_status}".encode()).hexdigest()[:24],
                "checked_at": checked_at,
                "content_hash": content_hash or None,
                "status": hydration_status,
            }
        except Exception as ex:  # noqa: BLE001
            hydration_status = f"parse_error:{type(ex).__name__}"
            checked_at = now_iso()
            check = {
                "check_id": "sercheck_"
                + sha256(f"{document_id}|{checked_at}|{hydration_status}".encode()).hexdigest()[:24],
                "checked_at": checked_at,
                "content_hash": content_hash or None,
                "status": hydration_status,
            }
    if (
        content_hash
        and raw_path_value
        and hydration_status in _COMPLETE_HYDRATION_STATUSES
    ):
        version_id = "server_" + sha256(f"{document_id}|{content_hash}".encode()).hexdigest()[:24]
        version = {
            "version_id": version_id,
            "content_hash": content_hash,
            "raw_path": raw_path_value,
            "extraction_status": extraction_status,
            "evidence": evidence,
            "created_at": first_seen_at,
            "supersedes_version_id": supersedes
            if supersedes and str(supersedes) != version_id
            else None,
            "make_current": True,
        }
    # Facts created for an already-known version remain immutable in the store.
    return {
        "document": {
            "document_id": document_id,
            "source_record_id": source_record_id,
            "symbol": str(metadata.get("symbol") or ""),
            "title": str(
                evidence.get("resolved_title")
                or (known or {}).get("title")
                or metadata.get("title")
                or ""
            ),
            "source_url": str(metadata.get("source_url") or ""),
            "published_at": metadata.get("published_at"),
            "first_seen_at": first_seen_at,
            "last_seen_at": first_seen_at,
            "withdrawn": _explicitly_withdrawn(metadata),
            "backfill_only": effective_backfill_only,
            "raw_metadata": metadata.get("raw_metadata") or {},
        },
        "version": version,
        "hydration_status": hydration_status,
        "facts": facts,
        "hypotheses": hypotheses,
        "check": check,
    }


def _run_serenity_once_owned(
    *,
    symbols: List[str] | None = None,
    lookback_days: int | None = None,
    bootstrap: bool = False,
    source_kind: str = "live",
    owner_id: str = "",
    client: CNInfoClient | None = None,
    verifier: ExchangeVerifier | None = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    cfg = load_config().serenity
    initialize_store()
    owner = str(owner_id or "")
    if not owner:
        raise RuntimeError("serenity_worker_owner_required")
    started_dt = now or datetime.now(timezone.utc)
    started_at = started_dt.isoformat()
    started_mono = time.monotonic()
    run_id = "serpoll_" + uuid.uuid4().hex
    source = "cninfo"
    injected_source = client is not None or verifier is not None
    if injected_source and source_kind in {"live", "bootstrap"}:
        effective_source_kind = "test"
    else:
        effective_source_kind = "bootstrap" if bootstrap and source_kind == "live" else source_kind
    cursor = load_cursor(source)
    target_meta = {"ok": True, "symbols": list(symbols or [])}
    if not symbols:
        target_meta = load_stable_targets()
        symbols = list(target_meta.get("symbols") or [])
    breaker = load_source_breaker(source)
    if breaker:
        try:
            breaker_until = datetime.fromisoformat(str(breaker.get("until_at") or "").replace("Z", "+00:00"))
            if breaker_until.tzinfo is None:
                breaker_until = breaker_until.replace(tzinfo=timezone.utc)
        except Exception:
            breaker_until = started_dt
        if breaker_until > started_dt:
            return {
                "status": "circuit_open",
                "complete": False,
                "reason": str(breaker.get("reason") or "source_breaker_open"),
                "source": source,
                "source_kind": effective_source_kind,
                "next_due_at": breaker_until.isoformat(),
                "schedule": {"delay_sec": max(1.0, (breaker_until - started_dt).total_seconds())},
                "target_meta": target_meta,
            }
    client = client or CNInfoClient(
        timeout_sec=cfg.request_timeout_sec,
        page_size=cfg.page_size,
        page_budget=cfg.page_budget,
        spacing_sec=cfg.request_spacing_sec,
    )
    verifier = verifier or ExchangeVerifier(timeout_sec=cfg.request_timeout_sec)
    clean_symbols = list(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip()))
    # Every live poll must re-observe the full evidence window that can still
    # affect Alpha; otherwise a 3-10 day old correction/withdrawal could be
    # missed while the older fact remained scoreable.
    days = max(
        1,
        int(
            lookback_days
            or (
                cfg.bootstrap_lookback_days
                if bootstrap
                else cfg.evidence_ttl_days
            )
        ),
    )
    end = started_dt.astimezone().date()
    start = end - timedelta(days=days)
    records: List[Dict[str, Any]] = []
    fetched_metadata: List[Dict[str, Any]] = []
    errors: List[str] = []
    complete = bool(clean_symbols)
    backlog = False
    retry_after: float | None = None
    rate_limited = False
    circuit_break = False
    fingerprints: List[str] = []
    source_progress = load_source_progress(source)
    coverage: List[Dict[str, Any]] = []
    progress_updates: List[Dict[str, Any]] = []
    symbol_windows: Dict[str, tuple[date, date]] = {}
    successful_symbol_fetches = 0
    local_symbol_failures = 0
    try:
        if not clean_symbols:
            raise SourceError("serenity_target_set_empty")
        stock_map = client.load_stock_map()
        for symbol in clean_symbols:
            if not heartbeat_worker_lease(owner):
                raise SourceError("serenity_worker_lease_lost")
            mapping = stock_map.get(symbol)
            if not mapping:
                local_symbol_failures += 1
                errors.append(f"{symbol}:stock_mapping_missing")
                coverage.append(
                    {
                        "symbol": symbol,
                        "metadata_complete": False,
                        "hydration_complete": False,
                        "item_count": 0,
                        "window_start": start.isoformat(),
                        "window_end": end.isoformat(),
                        "error": "stock_mapping_missing",
                    }
                )
                continue
            pending_progress = source_progress.get(symbol) if not bootstrap else None
            progress_matches_target = bool(
                pending_progress
                and str(pending_progress.get("target_id") or "")
                == str(target_meta.get("target_id") or "")
                and str(pending_progress.get("window_start") or "") == start.isoformat()
                and str(pending_progress.get("window_end") or "") == end.isoformat()
            )
            if progress_matches_target and str(pending_progress.get("status") or "") in {
                "backlog",
                "hydration_backlog",
            }:
                symbol_start = date.fromisoformat(str(pending_progress["window_start"]))
                symbol_end = date.fromisoformat(str(pending_progress["window_end"]))
                start_page = max(1, int(pending_progress.get("next_page") or 1))
            else:
                # Re-observe the full scoreable evidence window every live run.
                # A short cursor window would miss corrections/withdrawals to
                # still-active announcements and leave stale Alpha in ranking.
                symbol_start = start
                symbol_end = end
                start_page = 1
            symbol_windows[symbol] = (symbol_start, symbol_end)
            try:
                result = client.fetch_symbol(
                    symbol,
                    mapping["org_id"],
                    start=symbol_start,
                    end=symbol_end,
                    start_page=start_page,
                )
            except SourceError as ex:
                local_symbol_failures += 1
                global_failure = bool(
                    ex.schema_error or ex.status_code in {401, 403, 429}
                )
                if global_failure:
                    complete = False
                errors.append(f"{symbol}:{ex}")
                retry_after = ex.retry_after if ex.retry_after is not None else retry_after
                rate_limited = rate_limited or ex.status_code == 429
                circuit_break = circuit_break or ex.schema_error or ex.status_code in {401, 403}
                coverage.append(
                    {
                        "symbol": symbol,
                        "metadata_complete": False,
                        "hydration_complete": False,
                        "item_count": 0,
                        "window_start": symbol_start.isoformat(),
                        "window_end": symbol_end.isoformat(),
                        "error": str(ex)[:240],
                    }
                )
                if global_failure:
                    break
                continue
            successful_symbol_fetches += 1
            symbol_records = [
                {
                    **dict(item),
                    "_window_start": symbol_start.isoformat(),
                    "_window_end": symbol_end.isoformat(),
                }
                for item in list(result.get("records") or [])
            ]
            fetched_metadata.extend(symbol_records)
            complete = complete and bool(result.get("complete"))
            backlog = backlog or bool(result.get("backlog"))
            coverage.append(
                {
                    "symbol": symbol,
                    "metadata_complete": bool(result.get("complete")),
                    "hydration_complete": True,
                    "item_count": len(symbol_records),
                    "window_start": symbol_start.isoformat(),
                    "window_end": symbol_end.isoformat(),
                    "error": None,
                }
            )
            progress_updates.append(
                {
                    "symbol": symbol,
                    "window_start": symbol_start.isoformat(),
                    "window_end": symbol_end.isoformat(),
                    "next_page": result.get("next_page") or 1,
                    "status": "complete" if result.get("complete") else "backlog",
                }
            )
            if result.get("schema_fingerprint"):
                fingerprints.append(str(result["schema_fingerprint"]))
        if local_symbol_failures and successful_symbol_fetches == 0 and not fetched_metadata:
            complete = False
        first_seen = now_iso()
        for metadata in fetched_metadata:
            if not heartbeat_worker_lease(owner):
                raise SourceError("serenity_worker_lease_lost")
            record_start = date.fromisoformat(str(metadata.get("_window_start") or start.isoformat()))
            record_end = date.fromisoformat(str(metadata.get("_window_end") or end.isoformat()))
            records.append(
                _record_payload(
                    metadata=metadata,
                    first_seen_at=first_seen,
                    backfill_only=bool(bootstrap),
                    client=client,
                    verifier=verifier,
                    start=record_start,
                    end=record_end,
                    pdf_max_bytes=cfg.pdf_max_bytes,
                    content_revalidate_hours=cfg.content_revalidate_hours,
                )
            )
        extraction_failures = [
            str(record.get("hydration_status") or "")
            for record in records
            if str(record.get("hydration_status") or "")
            not in _COMPLETE_HYDRATION_STATUSES
        ]
        if extraction_failures:
            errors.append("document_extraction_incomplete:" + ",".join(extraction_failures[:5]))
            for item in coverage:
                symbol_failures = [
                    str(record.get("hydration_status") or "")
                    for record in records
                    if str((record.get("document") or {}).get("symbol") or "") == str(item.get("symbol") or "")
                    and str(record.get("hydration_status") or "")
                    not in _COMPLETE_HYDRATION_STATUSES
                ]
                if symbol_failures:
                    item["hydration_complete"] = False
                    item["error"] = "document_extraction_incomplete:" + ",".join(symbol_failures[:3])
                    for progress_item in progress_updates:
                        if str(progress_item.get("symbol") or "") == str(item.get("symbol") or ""):
                            progress_item["status"] = "hydration_backlog"
                            progress_item["next_page"] = 1
            if any(status == "parser_unavailable" for status in extraction_failures):
                complete = False
        verification_failures = [
            str((record.get("document") or {}).get("symbol") or "")
            for record in records
            if bool(((record.get("version") or {}).get("evidence") or {}).get("verification_required"))
            and not bool(((record.get("version") or {}).get("evidence") or {}).get("source_verified"))
        ]
        if verification_failures:
            complete = False
            errors.append(
                "secondary_verification_incomplete:"
                + ",".join(dict.fromkeys(verification_failures))
            )
            for item in coverage:
                if str(item.get("symbol") or "") in set(verification_failures):
                    item["hydration_complete"] = False
                    item["error"] = "secondary_verification_incomplete"
    except SourceError as ex:
        complete = False
        errors.append(str(ex))
        retry_after = ex.retry_after
        rate_limited = ex.status_code == 429
        circuit_break = ex.schema_error or ex.status_code in {401, 403}
    except Exception as ex:  # noqa: BLE001
        complete = False
        errors.append(f"{type(ex).__name__}:{ex}")
    latest_ids = dict(cursor.get("latest_ids") or {})
    for symbol in clean_symbols:
        ids = _record_ids(row for row in fetched_metadata if str(row.get("symbol") or "") == symbol)
        if ids:
            latest_ids[symbol] = ids[:10]
    symbol_last_complete_end = dict(cursor.get("symbol_last_complete_end") or {})
    for item in coverage:
        if item.get("metadata_complete") and item.get("hydration_complete"):
            symbol_last_complete_end[str(item.get("symbol") or "")] = str(item.get("window_end") or end.isoformat())
    next_cursor = {
        "latest_ids": latest_ids,
        "target_symbols": clean_symbols,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "symbol_last_complete_end": symbol_last_complete_end,
    }
    schema_fingerprint = (
        sha256("|".join(sorted(set(fingerprints))).encode()).hexdigest()[:16]
        if fingerprints
        else None
    )
    approved_fingerprint = str(cursor.get("_schema_fingerprint") or "")
    approved_contract_version = str(cursor.get("schema_contract_version") or "")
    schema_drift = bool(
        effective_source_kind in {"live", "bootstrap"}
        and approved_contract_version == _SCHEMA_CONTRACT_VERSION
        and approved_fingerprint
        and schema_fingerprint
        and schema_fingerprint != approved_fingerprint
    )
    if schema_drift:
        complete = False
        circuit_break = True
        errors.append(
            f"cninfo_schema_fingerprint_changed:{approved_fingerprint}->{schema_fingerprint}"
        )
        records = []
        for item in coverage:
            item["metadata_complete"] = False
            item["hydration_complete"] = False
            item["error"] = "schema_fingerprint_changed"
    if schema_fingerprint:
        next_cursor["schema_contract_version"] = _SCHEMA_CONTRACT_VERSION
    coverage_complete = bool(
        len(coverage) == len(clean_symbols)
        and coverage
        and all(
            bool(item.get("metadata_complete")) and bool(item.get("hydration_complete"))
            for item in coverage
        )
    )
    fetch_complete = bool(complete)
    source_complete = bool(fetch_complete and coverage_complete)
    elapsed = max(0.0, time.monotonic() - started_mono)
    history = recent_poll_outcomes(source, limit=cfg.cost_window)
    empty_count, failure_count = _next_consecutive_counts(
        history,
        source_complete=source_complete,
        item_count=len(fetched_metadata),
    )
    durations = recent_poll_durations(source, limit=cfg.cost_window)
    if source_complete:
        durations.append(elapsed)
    schedule = compute_schedule(
        last_elapsed_sec=elapsed,
        completed_durations=durations,
        now=started_dt,
        alpha=cfg.ewma_alpha,
        consecutive_complete_empty=empty_count,
        consecutive_failures=failure_count,
        retry_after_sec=retry_after,
        backlog=backlog,
        circuit_break=circuit_break,
        is_trading_day=compute_market_state(started_dt).is_trading_day,
    )
    finished_dt = datetime.now(timezone.utc)
    finished_at = finished_dt.isoformat()
    run = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_sec": elapsed,
        "status": (
            "success"
            if source_complete
            else "partial"
            if not circuit_break
            and (backlog or bool(fetched_metadata) or successful_symbol_fetches > 0)
            else "failed"
        ),
        "complete": source_complete,
        "request_count": client.request_count,
        "item_count": len(fetched_metadata),
        "next_due_at": next_due_at(finished_dt, schedule.delay_sec),
        "stale_after_sec": schedule.stale_after_sec,
        "error": ";".join(errors)[:1000] if errors else None,
        "target_id": target_meta.get("target_id"),
        "target_activation_revision": target_meta.get("activation_revision"),
    }
    stats = commit_poll(
        source=source,
        source_kind=effective_source_kind,
        run=run,
        records=records,
        cursor=next_cursor if source_complete else None,
        schema_fingerprint=schema_fingerprint,
        coverage=coverage,
        progress=progress_updates,
        lease_owner_id=owner,
    )
    bootstrap_id = None
    bootstrap_complete = bool(
        bootstrap
        and effective_source_kind == "bootstrap"
        and source_complete
        and days >= cfg.bootstrap_lookback_days
        and coverage
        and all(bool(item.get("metadata_complete")) and bool(item.get("hydration_complete")) for item in coverage)
    )
    if bootstrap:
        bootstrap_id = record_bootstrap_run(
            poll_run_id=run_id,
            source=source,
            symbols=clean_symbols,
            lookback_days=days,
            complete=bootstrap_complete,
            payload={
                "source_kind": effective_source_kind,
                "coverage": coverage,
                "schema_fingerprint": schema_fingerprint,
                "real_query": effective_source_kind == "bootstrap",
            },
        )
        if bootstrap_complete and effective_source_kind == "bootstrap":
            ensure_shadow_ready(bootstrap_id)
    if rate_limited and effective_source_kind in {"live", "bootstrap"}:
        set_source_breaker(
            source,
            reason="cninfo_rate_limited",
            until_at=str(run["next_due_at"]),
            sample_hash=schema_fingerprint,
        )
    elif circuit_break and effective_source_kind in {"live", "bootstrap"}:
        set_source_breaker(
            source,
            reason=";".join(errors)[:240] or "source_schema_or_access_breaker",
            until_at=(finished_dt + timedelta(seconds=cfg.circuit_breaker_sec)).isoformat(),
            sample_hash=schema_fingerprint,
        )
    elif source_complete and effective_source_kind in {"live", "bootstrap"}:
        clear_source_breaker(source)
    if effective_source_kind == "live" and source_complete:
        try:
            recover_operational_suspension_after_complete_poll()
        except Exception as ex:  # noqa: BLE001
            logger.error("[serenity] failed to recover source-health suspension: %s", ex)
    evaluation_report: Dict[str, Any] = {}
    if effective_source_kind == "live":
        try:
            evaluation_report = process_pending_evaluations()
        except Exception as ex:  # noqa: BLE001
            evaluation_report = {"error": f"{type(ex).__name__}:{ex}"}
            logger.warning("[serenity] matured evaluation processing failed: %s", ex)
    return {
        **run,
        "source": source,
        "source_kind": effective_source_kind,
        "symbols": clean_symbols,
        "target_meta": target_meta,
        "records": len(records),
        "stored": stats,
        "backlog": backlog,
        "schema_fingerprint": schema_fingerprint,
        "coverage": coverage,
        "bootstrap_id": bootstrap_id,
        "bootstrap_complete": bootstrap_complete,
        "schedule": {
            "cost_sec": schedule.cost_sec,
            "delay_sec": schedule.delay_sec,
            "stale_after_sec": schedule.stale_after_sec,
            "phase": schedule.phase,
        },
        "errors": errors,
        "evaluation": evaluation_report,
    }


def run_serenity_once(
    *,
    symbols: List[str] | None = None,
    lookback_days: int | None = None,
    bootstrap: bool = False,
    source_kind: str = "live",
    owner_id: str | None = None,
    manage_lease: bool = True,
    client: CNInfoClient | None = None,
    verifier: ExchangeVerifier | None = None,
    now: datetime | None = None,
) -> Dict[str, Any]:
    cfg = load_config().serenity
    initialize_store()
    owner = owner_id or f"once-{uuid.uuid4().hex}"
    if not manage_lease:
        return _run_serenity_once_owned(
            symbols=symbols,
            lookback_days=lookback_days,
            bootstrap=bootstrap,
            source_kind=source_kind,
            owner_id=owner,
            client=client,
            verifier=verifier,
            now=now,
        )
    if not acquire_worker_lease(owner):
        return {"status": "busy", "complete": False, "reason": "serenity_worker_lease_held"}
    heartbeater = _LeaseHeartbeater(owner, cfg.lease_sec)
    heartbeater.start()
    try:
        report = _run_serenity_once_owned(
            symbols=symbols,
            lookback_days=lookback_days,
            bootstrap=bootstrap,
            source_kind=source_kind,
            owner_id=owner,
            client=client,
            verifier=verifier,
            now=now,
        )
        heartbeater.assert_owned()
        return report
    finally:
        heartbeater.stop()
        release_worker_lease(owner)


def run_serenity_loop() -> None:
    cfg = load_config().serenity
    if cfg.mode == "off":
        logger.info("[serenity] mode=off; worker exits")
        return
    owner = f"worker-{uuid.uuid4().hex}"
    initialize_store()
    retry_delay = max(5.0, min(30.0, float(cfg.lease_sec) / 3.0))
    while True:
        if not acquire_worker_lease(owner):
            # A Compose recreate can begin before the stopped process's
            # persisted lease expires. Waiting inside this long-lived service
            # preserves the single-writer invariant without a crash/restart
            # loop or an unsafe lease takeover.
            logger.info("[serenity] worker lease held; retrying in %.0fs", retry_delay)
            time.sleep(retry_delay)
            continue
        heartbeater = _LeaseHeartbeater(owner, cfg.lease_sec)
        heartbeater.start()
        try:
            while True:
                heartbeater.assert_owned()
                bootstrap_required = latest_complete_bootstrap() is None
                report = _run_serenity_once_owned(
                    owner_id=owner,
                    bootstrap=bootstrap_required,
                )
                logger.info("[serenity] poll %s", json.dumps(report, ensure_ascii=False, separators=(",", ":"), default=str))
                if bootstrap_required and bool(report.get("bootstrap_complete")):
                    # A successful bootstrap establishes the causal starting
                    # point; immediately follow it with the first live target
                    # poll instead of leaving production pending for a full
                    # scheduler interval.
                    continue
                reported_target_id = str(
                    ((report.get("target_meta") or {}).get("target_id") or "")
                )
                allow_target_wakeup = str(report.get("status") or "") != "circuit_open"
                delay = float((report.get("schedule") or {}).get("delay_sec") or 60.0)
                # The selection worker owns publication of the immutable candidate
                # target.  Serenity must therefore observe that pointer while it is
                # waiting for the next source poll; otherwise a startup with no
                # target can sleep for an entire scheduler interval after the
                # worker publishes one.  Keep the lease heartbeat alive, check the
                # additive pointer at a bounded cadence, and contact the source
                # only after a new target is actually visible (or the normal due
                # time arrives).
                remaining = max(1.0, delay)
                while remaining > 0:
                    active_target_id = str(
                        (load_stable_targets().get("target_id") or "")
                    )
                    if (
                        allow_target_wakeup
                        and active_target_id
                        and active_target_id != reported_target_id
                    ):
                        logger.info(
                            "[serenity] target changed while waiting %s -> %s; polling immediately",
                            reported_target_id or "<none>",
                            active_target_id,
                        )
                        break
                    wait_step = min(retry_delay, remaining)
                    time.sleep(wait_step)
                    heartbeater.assert_owned()
                    remaining -= wait_step
                if remaining > 0:
                    continue
        finally:
            heartbeater.stop()
            release_worker_lease(owner)


def serenity_status() -> Dict[str, Any]:
    return status_snapshot()
