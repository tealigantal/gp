from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from ..core.config import load_config
from ..core.paths import store_dir
from .parser import PARSER_REVISION, build_verified_evidence, extract_pdf_document, supported_title_family
from .sources import CNInfoClient, ExchangeVerifier


POLICY_REVISION = "serenity_fixed_batch_3pct_v2_ocr"
FIXED_WEIGHT = 0.03
ZERO_REFERENCE = "serenity_zero_v2"


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def database_path() -> Path:
    configured = os.getenv("GP_SERENITY_CURRENT_DB")
    return Path(configured) if configured else store_dir() / "serenity" / "current.db"


def _connect(*, writable: bool) -> sqlite3.Connection:
    path = database_path()
    if writable:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, isolation_level=None, timeout=10)
    else:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if writable:
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


def initialize_store() -> Path:
    conn = _connect(writable=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        row = conn.execute("SELECT value FROM schema_metadata WHERE key='schema'").fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_metadata(key,value) VALUES('schema','serenity_current.v1')")
        elif str(row["value"]) != "serenity_current.v1":
            raise RuntimeError("serenity_store_schema_unsupported")
        conn.execute("CREATE TABLE IF NOT EXISTS targets(target_id TEXT PRIMARY KEY,payload_json TEXT NOT NULL,payload_digest TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS active_target(singleton INTEGER PRIMARY KEY CHECK(singleton=1),target_id TEXT NOT NULL REFERENCES targets(target_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS batches(batch_id TEXT PRIMARY KEY,target_id TEXT NOT NULL REFERENCES targets(target_id),content_digest TEXT NOT NULL,payload_json TEXT NOT NULL,completed_at TEXT NOT NULL,UNIQUE(target_id,content_digest))")
        conn.execute("CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY,symbol TEXT NOT NULL,source_record_id TEXT NOT NULL,first_seen_at TEXT NOT NULL,source_url TEXT NOT NULL,UNIQUE(symbol,source_record_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS document_versions(version_id TEXT PRIMARY KEY,document_id TEXT NOT NULL REFERENCES documents(document_id),content_digest TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(document_id,content_digest))")
        conn.execute("CREATE TABLE IF NOT EXISTS worker_lease(singleton INTEGER PRIMARY KEY CHECK(singleton=1),owner_id TEXT NOT NULL,expires_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS health(singleton INTEGER PRIMARY KEY CHECK(singleton=1),payload_json TEXT NOT NULL,updated_at TEXT NOT NULL)")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return database_path()


@dataclass(frozen=True)
class SerenityTarget:
    target_id: str
    market_session_date: str
    daily_evidence_date: str
    symbols: tuple[str, ...]
    base_scores: dict[str, float]
    observed_at: str


@dataclass(frozen=True)
class SerenityDecision:
    target_id: str
    reference_id: str | None
    semantic_revision: str
    applied_weight: float
    state: str
    alphas: dict[str, float]
    reasons: dict[str, tuple[str, ...]]
    reason_codes: tuple[str, ...]


def publish_target(
    symbols: Iterable[str],
    *,
    market_session_date: str,
    daily_evidence_date: str,
    universe_digest: str,
    base_scores: dict[str, float],
    observed_at: str,
) -> SerenityTarget:
    clean = tuple(sorted(dict.fromkeys(str(symbol).strip() for symbol in symbols if str(symbol).strip())))
    if not clean:
        raise ValueError("serenity_target_empty")
    payload = {
        "schema": "SerenityTarget.v1",
        "market_session_date": market_session_date,
        "daily_evidence_date": daily_evidence_date,
        "universe_digest": universe_digest,
        "symbols": list(clean),
        "base_scores": {symbol: round(float(base_scores[symbol]), 12) for symbol in clean},
        "policy_revision": POLICY_REVISION,
        "observed_at": observed_at,
    }
    semantic = {key: value for key, value in payload.items() if key != "observed_at"}
    target_id = "sertarget_" + _digest(semantic)[:24]
    initialize_store()
    conn = _connect(writable=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT OR IGNORE INTO targets(target_id,payload_json,payload_digest,created_at) VALUES(?,?,?,?)",
            (target_id, _canonical(payload), _digest(payload), observed_at),
        )
        conn.execute(
            "INSERT INTO active_target(singleton,target_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET target_id=excluded.target_id",
            (target_id,),
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return SerenityTarget(target_id, market_session_date, daily_evidence_date, clean, {s: float(base_scores[s]) for s in clean}, observed_at)


def _target_from_row(row: sqlite3.Row) -> SerenityTarget:
    payload = json.loads(str(row["payload_json"]))
    return SerenityTarget(
        target_id=str(row["target_id"]),
        market_session_date=str(payload["market_session_date"]),
        daily_evidence_date=str(payload["daily_evidence_date"]),
        symbols=tuple(str(item) for item in payload["symbols"]),
        base_scores={str(key): float(value) for key, value in dict(payload["base_scores"]).items()},
        observed_at=str(payload["observed_at"]),
    )


def load_active_target() -> SerenityTarget | None:
    if not database_path().exists():
        return None
    conn = _connect(writable=False)
    try:
        row = conn.execute("SELECT t.* FROM active_target a JOIN targets t ON t.target_id=a.target_id WHERE a.singleton=1").fetchone()
        return _target_from_row(row) if row else None
    finally:
        conn.close()


def load_decision(target: SerenityTarget) -> SerenityDecision:
    zero = SerenityDecision(
        target_id=target.target_id,
        reference_id=None,
        semantic_revision=f"{POLICY_REVISION}:{ZERO_REFERENCE}:{target.target_id}",
        applied_weight=0.0,
        state="degraded",
        alphas={symbol: 0.0 for symbol in target.symbols},
        reasons={symbol: ("serenity_batch_unavailable",) for symbol in target.symbols},
        reason_codes=("serenity_batch_unavailable",),
    )
    if not database_path().exists():
        return zero
    try:
        conn = _connect(writable=False)
        row = conn.execute(
            "SELECT batch_id,content_digest,payload_json FROM batches WHERE target_id=? AND completed_at<=? ORDER BY completed_at DESC,batch_id DESC LIMIT 1",
            (target.target_id, target.observed_at),
        ).fetchone()
        health_row = conn.execute("SELECT payload_json,updated_at FROM health WHERE singleton=1").fetchone()
    except sqlite3.Error:
        return zero
    finally:
        if "conn" in locals():
            conn.close()
    if row is None:
        return zero
    try:
        if health_row is None:
            return zero
        health = json.loads(str(health_row["payload_json"]))
        health_at = datetime.fromisoformat(str(health_row["updated_at"]))
        observed_at = datetime.fromisoformat(target.observed_at)
        if (
            str(health.get("state")) != "ready"
            or str(health.get("target_id")) != target.target_id
            or str(health.get("batch_id")) != str(row["batch_id"])
            or health_at > observed_at
            or (observed_at - health_at).total_seconds() > 900
        ):
            return zero
        payload = json.loads(str(row["payload_json"]))
        alphas = {str(key): max(-1.0, min(1.0, float(value))) for key, value in dict(payload["alphas"]).items()}
        if set(alphas) != set(target.symbols) or str(payload["target_id"]) != target.target_id:
            return zero
        reasons = {str(key): tuple(str(item) for item in value) for key, value in dict(payload["reasons"]).items()}
        return SerenityDecision(
            target_id=target.target_id,
            reference_id=str(row["batch_id"]),
            semantic_revision=f"{POLICY_REVISION}:{row['content_digest']}",
            applied_weight=FIXED_WEIGHT,
            state="active",
            alphas=alphas,
            reasons=reasons,
            reason_codes=("serenity_batch_complete", "serenity_fixed_weight_3pct"),
        )
    except (KeyError, TypeError, ValueError):
        return zero


def _set_health(state: str, *, target_id: str | None, detail: str | None = None, batch_id: str | None = None, updated_at: str | None = None) -> None:
    initialize_store()
    now = updated_at or datetime.now(UTC).isoformat()
    payload = {"mode": load_config().serenity.mode, "state": state, "target_id": target_id, "batch_id": batch_id, "detail": detail, "updated_at": now}
    conn = _connect(writable=True)
    try:
        conn.execute("INSERT INTO health(singleton,payload_json,updated_at) VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at", (_canonical(payload), now))
    finally:
        conn.close()


def status_snapshot() -> dict[str, Any]:
    base: dict[str, Any] = {"mode": load_config().serenity.mode, "state": "warming", "target_ready": False, "batch_ready": False, "detail": "worker_not_observed"}
    if not database_path().exists():
        return base
    try:
        conn = _connect(writable=False)
        row = conn.execute("SELECT payload_json FROM health WHERE singleton=1").fetchone()
        target = conn.execute("SELECT target_id FROM active_target WHERE singleton=1").fetchone()
        if row:
            stored = json.loads(str(row["payload_json"]))
            base.update({key: stored.get(key) for key in ("mode", "state", "detail", "updated_at")})
            base["batch_ready"] = bool(stored.get("batch_id")) and stored.get("state") == "ready"
        base["target_ready"] = bool(target)
        return base
    except sqlite3.Error as exc:
        return {**base, "state": "degraded", "detail": f"store:{type(exc).__name__}"}
    finally:
        if "conn" in locals():
            conn.close()


def _acquire_lease(owner_id: str, now: datetime, lease_sec: int) -> bool:
    initialize_store()
    conn = _connect(writable=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT owner_id,expires_at FROM worker_lease WHERE singleton=1").fetchone()
        available = row is None or datetime.fromisoformat(str(row["expires_at"])) <= now or str(row["owner_id"]) == owner_id
        if available:
            conn.execute("INSERT INTO worker_lease(singleton,owner_id,expires_at) VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET owner_id=excluded.owner_id,expires_at=excluded.expires_at", (owner_id, (now + timedelta(seconds=lease_sec)).isoformat()))
        conn.execute("COMMIT")
        return available
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _release_lease(owner_id: str) -> None:
    conn = _connect(writable=True)
    try:
        conn.execute("DELETE FROM worker_lease WHERE singleton=1 AND owner_id=?", (owner_id,))
    finally:
        conn.close()


def _commit_batch(target: SerenityTarget, payload: dict[str, Any], documents: list[dict[str, Any]], completed_at: str) -> str:
    content = {key: value for key, value in payload.items() if key != "completed_at"}
    content_digest = _digest(content)
    batch_id = "serbatch_" + content_digest[:24]
    conn = _connect(writable=True)
    try:
        conn.execute("BEGIN IMMEDIATE")
        for item in documents:
            conn.execute("INSERT OR IGNORE INTO documents(document_id,symbol,source_record_id,first_seen_at,source_url) VALUES(?,?,?,?,?)", (item["document_id"], item["symbol"], item["source_record_id"], item["first_seen_at"], item["source_url"]))
            conn.execute("INSERT OR IGNORE INTO document_versions(version_id,document_id,content_digest,payload_json,created_at) VALUES(?,?,?,?,?)", (item["version_id"], item["document_id"], item["content_digest"], _canonical(item), completed_at))
        conn.execute("INSERT OR IGNORE INTO batches(batch_id,target_id,content_digest,payload_json,completed_at) VALUES(?,?,?,?,?)", (batch_id, target.target_id, content_digest, _canonical(payload), completed_at))
        conn.execute("COMMIT")
        return batch_id
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _document_first_seen_at(document_id: str) -> str | None:
    if not database_path().exists():
        return None
    conn = _connect(writable=False)
    try:
        row = conn.execute("SELECT first_seen_at FROM documents WHERE document_id=?", (document_id,)).fetchone()
        return str(row["first_seen_at"]) if row else None
    finally:
        conn.close()


def collect_once(*, now: datetime | None = None, client: CNInfoClient | None = None, verifier: ExchangeVerifier | None = None) -> dict[str, Any]:
    cfg = load_config().serenity
    if cfg.mode == "off":
        _set_health("off", target_id=None, detail="serenity_disabled")
        return {"state": "off"}
    clock = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    owner_id = f"worker-{os.getpid()}"
    if not _acquire_lease(owner_id, clock, max(cfg.lease_sec, 3600)):
        _set_health("warming", target_id=None, detail="lease_held", updated_at=clock.isoformat())
        return {"state": "busy"}
    try:
        target = load_active_target()
        if target is None:
            _set_health("warming", target_id=None, detail="target_unavailable", updated_at=clock.isoformat())
            return {"state": "warming", "reason": "target_unavailable"}
        source = client or CNInfoClient(timeout_sec=cfg.request_timeout_sec, page_size=cfg.page_size, page_budget=cfg.page_budget, spacing_sec=cfg.request_spacing_sec)
        exchange = verifier or ExchangeVerifier(timeout_sec=cfg.request_timeout_sec)
        stock_map = source.load_stock_map()
        start = date.fromisoformat(target.daily_evidence_date) - timedelta(days=cfg.evidence_ttl_days)
        end = min(clock.date(), date.fromisoformat(target.market_session_date))
        symbol_facts: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in target.symbols}
        documents: list[dict[str, Any]] = []
        for symbol in target.symbols:
            stock = stock_map.get(symbol)
            if not stock:
                raise RuntimeError(f"symbol_mapping_missing:{symbol}")
            page = source.fetch_symbol(symbol, stock["org_id"], start=start, end=end)
            if not bool(page.get("complete")):
                raise RuntimeError(f"pagination_incomplete:{symbol}")
            for record in list(page.get("records") or []):
                title = str(record.get("title") or "")
                title_family = supported_title_family(title)
                if title_family is None:
                    continue
                published_at = str(record.get("published_at") or "")
                published_clock = datetime.fromisoformat(published_at)
                if published_clock > clock:
                    continue
                if not exchange.verify(record, start=start, end=end):
                    raise RuntimeError(f"exchange_verification_failed:{symbol}")
                pdf = source.download_pdf(str(record["source_url"]), max_bytes=cfg.pdf_max_bytes)
                parse_result = extract_pdf_document(
                    pdf,
                    symbol=symbol,
                    title=title,
                    max_pages=40,
                    max_chars=250_000,
                    timeout_sec=240.0,
                    primary_dpi=200,
                    verify_dpi=300,
                    max_page_pixels=20_000_000,
                    max_total_pixels=160_000_000,
                    page_timeout_sec=8.0,
                )
                if parse_result.state != "parsed":
                    raise RuntimeError(f"pdf_{parse_result.state}:{symbol}")
                text = parse_result.text
                content_digest = sha256(pdf).hexdigest()
                document_id = "serdoc_" + sha256(f"cninfo|{record['source_record_id']}".encode()).hexdigest()[:24]
                version_id = "server_" + sha256(f"{document_id}|{content_digest}".encode()).hexdigest()[:24]
                first_seen_at = _document_first_seen_at(document_id) or clock.isoformat()
                facts, _ = build_verified_evidence(
                    symbol=symbol,
                    title=title,
                    text=text,
                    published_at=published_at,
                    effective_available_at=first_seen_at,
                    source_document_id=document_id,
                    source_version_id=version_id,
                    source_url=str(record["source_url"]),
                    content_hash=content_digest,
                    source_verified=True,
                    backfill_only=False,
                )
                item = {
                    "document_id": document_id,
                    "version_id": version_id,
                    "symbol": symbol,
                    "source_record_id": str(record["source_record_id"]),
                    "source_url": str(record["source_url"]),
                    "title": title,
                    "title_family": title_family,
                    "published_at": published_at,
                    "first_seen_at": first_seen_at,
                    "content_digest": content_digest,
                    "parse_method": parse_result.parse_method,
                    "parser_revision": parse_result.parser_revision,
                    "ocr_engine": parse_result.ocr_engine,
                    "ocr_confidence": parse_result.ocr_confidence,
                    "facts": [fact.model_dump(mode="json") for fact in facts],
                }
                documents.append(item)
                symbol_facts[symbol].extend(item["facts"])
        alphas: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        for symbol in target.symbols:
            facts = symbol_facts[symbol]
            directional = [fact for fact in facts if int(fact["direction"]) != 0]
            strength = sum(float(fact["confidence"]) * float(fact["source_quality"]) for fact in directional)
            signed = sum(int(fact["direction"]) * float(fact["confidence"]) * float(fact["source_quality"]) for fact in directional)
            alpha = max(-1.0, min(1.0, signed / strength)) if strength else 0.0
            alphas[symbol] = round(alpha, 12)
            reasons[symbol] = ["serenity_verified_positive" if alpha > 0 else "serenity_verified_negative" if alpha < 0 else "serenity_no_relevant_evidence"]
        completed_at = clock.isoformat()
        payload = {
            "schema": "SerenityBatch.v1",
            "target_id": target.target_id,
            "completed_at": completed_at,
            "policy_revision": POLICY_REVISION,
            "parser_revision": PARSER_REVISION,
            "alphas": alphas,
            "reasons": reasons,
            "document_version_ids": sorted(item["version_id"] for item in documents),
            "document_parse_audit": {
                item["version_id"]: {
                    "parse_method": item["parse_method"],
                    "parser_revision": item["parser_revision"],
                    "ocr_engine": item["ocr_engine"],
                    "ocr_confidence": item["ocr_confidence"],
                }
                for item in documents
            },
        }
        batch_id = _commit_batch(target, payload, documents, completed_at)
        _set_health("ready", target_id=target.target_id, batch_id=batch_id, updated_at=completed_at)
        return {"state": "ready", "target_id": target.target_id, "batch_id": batch_id, "symbol_count": len(target.symbols), "document_count": len(documents)}
    except Exception as exc:
        target_id = target.target_id if "target" in locals() and target is not None else None
        _set_health("degraded", target_id=target_id, detail=f"{type(exc).__name__}:{exc}", updated_at=clock.isoformat())
        return {"state": "degraded", "target_id": target_id, "error": f"{type(exc).__name__}:{exc}"}
    finally:
        _release_lease(owner_id)


def run_loop(*, interval_sec: int = 300) -> None:
    failure_delay = max(30, int(interval_sec))
    while True:
        try:
            report = collect_once()
        except Exception as exc:
            target = load_active_target()
            _set_health("degraded", target_id=target.target_id if target else None, detail=f"worker:{type(exc).__name__}:{exc}")
            report = {"state": "degraded", "error": f"{type(exc).__name__}:{exc}"}
        print(json.dumps({"serenity": report}, ensure_ascii=False, separators=(",", ":")), flush=True)
        if str(report.get("state")) == "ready":
            failure_delay = max(30, int(interval_sec))
            delay = failure_delay
        else:
            delay = failure_delay
            failure_delay = min(900, failure_delay * 2)
        time.sleep(delay)
