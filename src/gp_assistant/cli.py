from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import time

import uvicorn

from .gateway.app import app
from .migrate_contracts import migrate
from .application.market_orchestrator import MarketDayOrchestrator
from .store import ContractStore
from .serenity.service import publish_target as publish_serenity_target
from .serenity.service import run_loop as run_serenity_loop
from datetime import datetime
from zoneinfo import ZoneInfo


def _seed_serenity_target_from_current_plan(store: ContractStore, now: datetime) -> None:
    publication = store.current_publication()
    plan = store.load_plan(publication.plan_id) if publication else None
    if plan is None or plan.daily_evidence_date is None or not plan.candidate_universe.complete or plan.serenity.applied_weight != 0.0:
        return
    finalists = tuple(
        item
        for item in plan.evaluated_candidates
        if any(expert.expert == "serenity" for expert in item.experts)
    )
    if len(finalists) != 30:
        return

    def base_score(item) -> float:
        lunch_change = sum(expert.contribution for expert in item.experts if expert.expert == "intraday_5m")
        return round(float(item.adaptive_score) - float(lunch_change), 12)

    if not finalists:
        return
    publish_serenity_target(
        (item.symbol for item in finalists),
        market_session_date=plan.market_session_date.isoformat(),
        daily_evidence_date=plan.daily_evidence_date.isoformat(),
        universe_digest=plan.candidate_universe.content_digest,
        base_scores={item.symbol: base_score(item) for item in finalists},
        observed_at=now.isoformat(),
    )


def _worker_tick(
    store: ContractStore,
    *,
    now: datetime,
    orchestrator: MarketDayOrchestrator | None = None,
) -> dict[str, object]:
    """One pure scheduling heartbeat; all collection remains worker-owned."""
    active = orchestrator or MarketDayOrchestrator(store)
    return active.tick(now=now)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gp-assistant")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    cutover = commands.add_parser("migrate-contracts")
    cutover.add_argument("--database", required=True)
    worker = commands.add_parser("worker")
    worker.add_argument("--runtime-interval-sec", type=int, default=60)
    args = parser.parse_args(argv)
    if args.command == "serve":
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "migrate-contracts":
        print(json.dumps(migrate(args.database), ensure_ascii=False, indent=2))
    else:
        worker_store = ContractStore()
        worker_orchestrator = MarketDayOrchestrator(worker_store)
        serenity_process = None
        serenity_restart_after = 0.0
        while True:
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            if os.getenv("GP_SERENITY_MODE", "native").strip().lower() != "off":
                if serenity_process is None or not serenity_process.is_alive():
                    if time.monotonic() >= serenity_restart_after:
                        if serenity_process is not None:
                            serenity_process.join(timeout=0.1)
                            print(json.dumps({"serenity_process_exit": serenity_process.exitcode}, ensure_ascii=False), flush=True)
                        try:
                            _seed_serenity_target_from_current_plan(ContractStore(), now)
                        except Exception as exc:  # noqa: BLE001
                            print(json.dumps({"serenity_target_seed_error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False), flush=True)
                        serenity_process = multiprocessing.Process(
                            target=run_serenity_loop,
                            kwargs={"interval_sec": int(os.getenv("GP_SERENITY_POLL_INTERVAL_SEC", "60"))},
                            name="gp-serenity",
                            daemon=False,
                        )
                        serenity_process.start()
                        serenity_restart_after = time.monotonic() + 30.0
            try:
                tick = _worker_tick(
                    worker_store,
                    now=now,
                    orchestrator=worker_orchestrator,
                )
                print(json.dumps({"market_day": tick}, ensure_ascii=False), flush=True)
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"worker_error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False), flush=True)
            time.sleep(max(10, args.runtime_interval_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
