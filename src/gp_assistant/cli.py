from __future__ import annotations

import argparse
import json
import time

import uvicorn

from .gateway.app import app
from .migrate_contracts import migrate
from .application.real_producer import RealRecommendationProducer
from .application.runtime_producer import RuntimeRecommendationProducer
from .store import ContractStore
from datetime import datetime
from zoneinfo import ZoneInfo


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
        last_plan_at = None
        while True:
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            try:
                if last_plan_at is None or (now - last_plan_at).total_seconds() >= max(60, args.plan_interval_sec):
                    RealRecommendationProducer(ContractStore()).produce(now, refresh_daily=True)
                    last_plan_at = now
                RuntimeRecommendationProducer(ContractStore()).produce(now=now)
            except Exception as exc:  # noqa: BLE001
                print(json.dumps({"worker_error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False), flush=True)
            time.sleep(max(10, args.runtime_interval_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
