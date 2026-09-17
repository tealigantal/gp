"""Read-only audit of canonical plans; publication snapshots are not samples."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import statistics


def stats(values):
    values = list(values)
    if not values:
        return {"count": 0}
    return dict(count=len(values), minimum=min(values), maximum=max(values),
                mean=statistics.mean(values), median=statistics.median(values),
                stddev=statistics.pstdev(values))


def analyze(database: Path):
    conn = sqlite3.connect(database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        rows = conn.execute("SELECT plan_id,payload_json FROM recommendation_plans ORDER BY plan_id").fetchall()
        publications = conn.execute("SELECT count(*) FROM recommendation_publications").fetchone()[0]
        conn.rollback()
    finally:
        conn.close()
    plans = [json.loads(payload) for _, payload in rows]
    daily = [p for p in plans if p["producer"]["name"] == "real_daily_producer" and p["evaluated_candidates"]]
    latest = {}
    for plan in sorted(daily, key=lambda p: (datetime.fromisoformat(p["generated_at"]), p["plan_id"])):
        latest[plan["market_session_date"]] = plan
    candidates = [c for p in latest.values() for c in p["evaluated_candidates"]]
    chosen = [c for c in candidates if c["disposition"] == "selected"]
    terms = []
    for c in chosen:
        win = 50 * c["probability"]["probability"]
        confidence = 20 * c["probability"]["confidence"]
        drawdown = -20 * (1 - c["risk"]["score"])
        serenity = 100 * sum(e["contribution"] for e in c["experts"] if e["expert"] == "serenity")
        execution = 100 * c["adaptive_score"] - win - confidence - drawdown - serenity
        terms.append(dict(win=win, confidence=confidence, drawdown=drawdown, serenity=serenity, execution_derived=execution))
    top_rows = []
    for day, plan in sorted(latest.items()):
        top = sorted((c for c in plan["evaluated_candidates"] if c["disposition"] == "selected"), key=lambda c: (-c["adaptive_score"], c["symbol"]))
        top_rows.append(dict(day=day, plan_id=plan["plan_id"], generated_at=plan["generated_at"],
            scored=len(plan["evaluated_candidates"]), eligible=plan["candidate_universe"]["eligible_count"],
            gap12=100 * (top[0]["adaptive_score"] - top[1]["adaptive_score"]) if len(top) > 1 else None,
            selected=[dict(symbol=c["symbol"], score=100*c["adaptive_score"], probability=c["probability"]["probability"], ranking=c["ranking"]["score"]) for c in top]))
    gaps = [r["gap12"] for r in top_rows if r["gap12"] is not None]
    return dict(total_plans=len(plans), total_publications=publications, nonempty_daily_plans=len(daily),
        payload_sha256=hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest(),
        daily_sessions=len(latest), candidates=stats(100*c["adaptive_score"] for c in candidates),
        selected=stats(100*c["adaptive_score"] for c in chosen),
        selected_60_65=sum(60 <= 100*c["adaptive_score"] <= 65 for c in chosen),
        confidence=stats(c["probability"]["confidence"] for c in chosen),
        effective_samples=stats(c["probability"]["effective_sample_size"] for c in chosen),
        components={k: stats(t[k] for t in terms) for k in terms[0]} if terms else {},
        component_limit="Execution is algebraically inferred assuming the current daily formula; not independently persisted. No realized-return or calibration test.",
        gap12=stats(gaps), gap12_below_one=sum(g < 1 for g in gaps), plans=top_rows)


def memory_summary(database: Path):
    conn = sqlite3.connect(database.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    try:
        conn.execute("BEGIN")
        count, last_signal, last_outcome, last_created = conn.execute(
            "SELECT count(*),max(signal_trading_day),max(outcome_available_trading_day),max(created_at) FROM market_events"
        ).fetchone()
        pools = {}
        for day in ("2026-07-22", "2026-09-11"):
            rows = conn.execute("SELECT event_id,signal_trading_day,symbol,market_context_json FROM market_events WHERE signal_trading_day<? AND outcome_complete=1 AND outcome_available_trading_day<? ORDER BY signal_trading_day DESC LIMIT 4000", (day, day)).fetchall()
            pools[day] = dict(count=len(rows), signal_min=min(r[1] for r in rows) if rows else None,
                signal_max=max(r[1] for r in rows) if rows else None, symbols=len({r[2] for r in rows}),
                regimes=sorted({json.loads(r[3])["market_regime"] for r in rows}),
                event_set_sha256=hashlib.sha256(json.dumps(sorted(r[0] for r in rows)).encode()).hexdigest())
        return dict(count=count, last_signal=last_signal, last_outcome=last_outcome, last_created=last_created, pools=pools)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--memory-database", type=Path)
    args = parser.parse_args()
    report = analyze(args.database)
    if args.memory_database:
        report["market_memory"] = memory_summary(args.memory_database)
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
