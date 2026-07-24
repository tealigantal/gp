from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import time

import uvicorn

from .gateway.app import app
from .migrate_contracts import migrate
from .application.real_producer import RealRecommendationProducer
from .application.lunch_rebalance_producer import LunchRebalanceProducer, is_lunch_plan
from .application.runtime_producer import RuntimeRecommendationProducer, market_phase
from .contracts.catalog import MarketPhase
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
    last_plan_at: datetime | None,
    plan_interval_sec: int,
    real_producer: RealRecommendationProducer | None = None,
    runtime_producer: RuntimeRecommendationProducer | None = None,
    lunch_producer: LunchRebalanceProducer | None = None,
) -> datetime | None:
    phase = market_phase(now)
    current_publication = store.current_publication()
    current_plan = store.load_plan(current_publication.plan_id) if current_publication else None
    current_session_ready = bool(current_plan and current_plan.market_session_date == now.date())
    plan_due = last_plan_at is None or (now - last_plan_at).total_seconds() >= max(60, plan_interval_sec)
    real = real_producer or RealRecommendationProducer(store)
    runtime = runtime_producer or RuntimeRecommendationProducer(store)
    lunch = lunch_producer or LunchRebalanceProducer(store)

    if phase is MarketPhase.LUNCH:
        if not current_session_ready:
            real.produce(now, refresh_daily=True)
            last_plan_at = now
        result = lunch.produce(now=now)
        if result.state not in {"published", "reused"}:
            print(json.dumps({"lunch_rebalance": result.state, "reason": result.reason}, ensure_ascii=False), flush=True)
        return last_plan_at

    lunch_plan_current = bool(
        current_session_ready
        and is_lunch_plan(current_plan)
        and phase in {MarketPhase.AFTERNOON, MarketPhase.CLOSING_AUCTION}
    )
    if plan_due and not lunch_plan_current:
        real.produce(now, refresh_daily=True)
        last_plan_at = now
    runtime.produce(now=now)
    return last_plan_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gp-assistant")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    cutover = commands.add_parser("migrate-contracts")
    cutover.add_argument("--database", required=True)
    commands.add_parser("refresh-plan")
    commands.add_parser("refresh-daily")
    commands.add_parser("refresh-runtime")
    worker = commands.add_parser("worker")
    worker.add_argument("--plan-interval-sec", type=int, default=1800)
    worker.add_argument("--runtime-interval-sec", type=int, default=60)
    args = parser.parse_args(argv)
    if args.command == "serve":
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.command == "migrate-contracts":
        print(json.dumps(migrate(args.database), ensure_ascii=False, indent=2))
    elif args.command == "refresh-plan":
        print(RealRecommendationProducer(ContractStore()).produce(datetime.now(ZoneInfo("Asia/Shanghai"))).plan.model_dump_json())
    elif args.command == "refresh-daily":
        print(RealRecommendationProducer(ContractStore()).produce(datetime.now(ZoneInfo("Asia/Shanghai")), refresh_daily=True).plan.model_dump_json())
    elif args.command == "refresh-runtime":
        print(RuntimeRecommendationProducer(ContractStore()).produce(now=datetime.now(ZoneInfo("Asia/Shanghai"))).model_dump_json())
    else:
        worker_store = ContractStore()
        serenity_process = None
        serenity_restart_after = 0.0
        last_plan_at = None
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
                last_plan_at = _worker_tick(
                    worker_store,
                    now=now,
                    last_plan_at=last_plan_at,
                    plan_interval_sec=args.plan_interval_sec,
                )
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"worker_error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False), flush=True)
            time.sleep(max(10, args.runtime_interval_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
