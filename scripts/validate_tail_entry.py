"""Small real-data/real-model experiment; isolated contract database only.

Run from repo root: PYTHONPATH=src python scripts/validate_tail_entry.py
Never writes the production store or uses historical data as a live fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, time
import requests

from gp_assistant.application.entry_service import EntryService
from gp_assistant.application.conversation_service import ConversationService
from gp_assistant.application.publication_service import PublicationService
from gp_assistant.application.trading_calendar import load_cn_a_calendar
from gp_assistant.contracts.decision import RecommendationPlan
from gp_assistant.llm.client import LLMClient
from gp_assistant.providers.sina_minutes import SinaMinuteProvider, SHANGHAI, SOURCE
from gp_assistant.store import ContractStore


def main():
    out = Path("reports/tail-entry-20260927")
    out.mkdir(parents=True, exist_ok=True)
    working = Path("results/tail-entry-experiment-20260927")
    working.mkdir(parents=True, exist_ok=True)
    os.environ["GP_STORE_DIR"] = str(working)
    now = datetime.now(SHANGHAI)
    calendar = load_cn_a_calendar()
    day = calendar.previous_open_on_or_before(now.date())
    publication = requests.get("http://127.0.0.1:8000/api/recommendation/current", timeout=10).json()
    # Read-only export of exactly the current canonical plan, no credentials.
    command = "import sqlite3; c=sqlite3.connect('file:/app/store/agent.db?mode=ro',uri=True); print(c.execute('SELECT payload_json FROM recommendation_plans WHERE plan_id=?',(" + repr(publication["plan_id"]) + ",)).fetchone()[0])"
    exported = subprocess.check_output(["docker", "compose", "exec", "-T", "gp", "python", "-c", command], text=True, encoding="utf-8")
    plan = RecommendationPlan.model_validate_json(exported)
    store = ContractStore(working / f"contracts-{now:%H%M%S}.sqlite")
    (out / "plan-facts.json").write_text(json.dumps({"plan_id": plan.plan_id, "session": str(plan.market_session_date), "generated_at": plan.generated_at.isoformat(), "candidates": [c.model_dump(mode="json") for c in plan.evaluated_candidates if c.disposition.value == "selected"]}, ensure_ascii=False, indent=2), encoding="utf-8")
    store.commit_plan(plan)
    PublicationService(store).publish(plan_id=plan.plan_id, runtime_id=None, published_at=plan.generated_at)
    symbols = [c.symbol for c in plan.evaluated_candidates if c.disposition.value == "selected"][:2]
    provider = SinaMinuteProvider()
    records, frames = {}, {}
    for symbol in [*symbols, "000300"]:
        try:
            frame, fetched_at, elapsed = provider.fetch(symbol, index=symbol == "000300")
            sample = frame[frame.trade_time.str.startswith(str(day))]
            (out / f"raw-{symbol}-{day}.json").write_text(sample.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
            frames[symbol] = (frame, fetched_at, elapsed)
            records[symbol] = {"source": SOURCE, "fetched_at": fetched_at.isoformat(), "request_ms": elapsed, "raw_rows": len(frame), "sample_rows": len(sample), "raw_start": frame.iloc[0].trade_time, "raw_end": frame.iloc[-1].trade_time, "stock_volume_unit": "shares" if symbol != "000300" else "unused", "amount_unit": "CNY", "price_basis": "unadjusted"}
        except (requests.RequestException, ValueError) as exc:
            records[symbol] = {"error": f"{type(exc).__name__}:{exc}"}
    (out / "requests.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    model = LLMClient()
    service = EntryService(store, model=model, calendar=calendar)
    assessments = []
    for minute in (40, 50):
        cutoff = datetime.combine(day, time(14, minute), tzinfo=SHANGHAI)
        for symbol in symbols:
            if symbol not in frames:
                continue
            frame, fetched_at, elapsed = frames[symbol]
            result = service.assess(plan_id=plan.plan_id, symbol=symbol, scenario="new_position", now=cutoff, mode="historical", frame=frame, benchmark=frames["000300"][0] if "000300" in frames else None, fetched_at=fetched_at, request_ms=elapsed)
            assessments.append({"judgment_time": cutoff.isoformat(), "symbol": symbol, "used_times": [str(t) for t in frame.trade_time if str(day) + " 09:35:00" <= str(t) <= cutoff.strftime("%Y-%m-%d %H:%M:%S")], "result": result})
            print(json.dumps({"symbol": symbol, "cutoff": cutoff.isoformat(), "state": result["state"], "error": result["error"]}, ensure_ascii=False), flush=True)
    (out / "assessments.json").write_text(json.dumps({"plan_id": plan.plan_id, "plan_session": str(plan.market_session_date), "plan_generated_at": plan.generated_at.isoformat(), "full_historical_decision_replay": plan.generated_at <= datetime.combine(day, time(14, 40), tzinfo=SHANGHAI) and plan.market_session_date == day, "intraday_availability_verified": False, "model": model.model, "results": assessments}, ensure_ascii=False, indent=2), encoding="utf-8")
    # The real current-clock dialogue must reject historical minutes as current.
    # Trace the actual supplier tool calls; never store auth headers/keys.
    trace = []
    original = model.run_chat_with_tools
    def traced(messages, *args, **kwargs):
        response = original(messages, *args, **kwargs)
        trace.append({"history_roles": [m["role"] for m in messages], "response": response})
        return response
    model.run_chat_with_tools = traced
    conversation = ConversationService(store, narrator=model, entry_service=service)
    dialogues = []
    session = f"real-tail-{now:%Y%m%d%H%M%S}"
    for number, question in enumerate(["你好", "第一只现在能买吗？", "那第二只呢？", "重新看一下。", "刚才不是说走弱了吗？", "继续。", "我已经买了一部分，还适合加吗？"]):
        try:
            answer = conversation.reply(session_id=session, client_turn_id=str(number), user_message=question)
            dialogues.append({"question": question, "reply": answer["reply"]})
            print(json.dumps({"question": question, "ok": True}, ensure_ascii=False), flush=True)
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            dialogues.append({"question": question, "error": f"{type(exc).__name__}:{exc}"})
            print(json.dumps(dialogues[-1], ensure_ascii=False), flush=True)
    (out / "dialogues.json").write_text(json.dumps({"observed_at": now.isoformat(), "model": model.model, "dialogues": dialogues, "tool_trace": trace}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
