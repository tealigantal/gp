from __future__ import annotations

from datetime import datetime, time, timedelta
from hashlib import sha256
import json
from time import monotonic
import requests

from ..contracts.entry import EntryAssessment, EntryJudgment, EntryScenario
from ..intraday.entry_evidence import BAR_INTERVAL, PUBLICATION_LAG, build_evidence, fresh, latest_closed_boundary
from ..llm.client import LLMClient
from ..providers.sina_minutes import SinaMinuteProvider, SHANGHAI
from ..store import ContractStore
from .process_lock import CrossProcessLock, OperationBusy
from .trading_calendar import load_cn_a_calendar
from .market_runs import MarketRunStore

REFRESH_SECONDS = 60


def failure_message(reason: str | None) -> str:
    if reason == "outside_tail_entry_window":
        return "当前不在交易日14:35至14:57的尾盘评估窗口内。"
    if reason == "plan_session_mismatch":
        return "所依据的计划不属于当前交易日，不能用于当前入场确认。"
    if reason == "ValueError:confirmed_suspension":
        return "已核验该股票当日停牌，不具备交易条件；未生成分钟走势判断。"
    return "本次未取得有效行情或模型确认，不能据此判断走弱或适合买入。"


def entry_window(now, calendar):
    return calendar.is_open(now.date()) and time(14, 35) <= now.time() < time(14, 57)


class EntryService:
    """Single formal assessment writer, shared by worker and conversation tools."""

    def __init__(self, store: ContractStore, *, provider=None, model=None, calendar=None, market_runs=None):
        self.store = store
        self.provider = provider or SinaMinuteProvider()
        self.model = model or LLMClient()
        self.calendar = calendar or load_cn_a_calendar()
        self.market_runs = market_runs or MarketRunStore()

    def read(self, plan_id, symbol, scenario, *, now):
        history = self.store.entry_history(plan_id, symbol, scenario, before=now)
        latest = history[0] if history else None
        attempt = self.store.entry_attempt(plan_id, symbol, scenario)
        current = bool(latest and latest.mode == "live" and entry_window(now, self.calendar) and fresh(latest.evidence.cutoff, now))
        state = "ready" if current else "stale" if latest else "unavailable"
        if attempt and (latest is None or attempt["attempted_at"] >= latest.assessed_at.isoformat()):
            if attempt["state"] != "ready":
                state = attempt["state"]
                current = False
                if state == "refreshing" and now - datetime.fromisoformat(attempt["attempted_at"]) > timedelta(seconds=60):
                    state = "unavailable"
        valid_until = min(latest.evidence.cutoff + BAR_INTERVAL + PUBLICATION_LAG, now.replace(hour=14, minute=57, second=0, microsecond=0)) if latest else None
        error = attempt["error"] if attempt else None
        if current and self.market_runs.confirmed_suspension_at(symbol=symbol, now=now):
            current, state, error = False, "unavailable", "ValueError:confirmed_suspension"
        return {"state": state, "current": current, "valid_until": valid_until.isoformat() if valid_until else None, "error": error, "message": failure_message(error) if not current else None,
                "assessment": latest.model_dump(mode="json") if latest else None,
                "previous": history[1].model_dump(mode="json") if len(history) > 1 else None}

    def assess(self, *, plan_id: str, symbol: str, scenario: EntryScenario, now: datetime, mode="live", frame=None, benchmark=None, fetched_at=None, request_ms=0):
        if now.tzinfo is None:
            raise ValueError("entry_timezone_required")
        now = now.astimezone(SHANGHAI)
        if scenario not in {"new_position", "add_position"} or mode not in {"live", "historical"}:
            raise ValueError("entry_scenario_invalid")
        plan = self.store.load_plan(plan_id)
        if plan is None:
            raise ValueError("plan_not_found")
        candidate = next((c for c in plan.evaluated_candidates if c.symbol == symbol), None)
        if candidate is None:
            raise ValueError("entry_symbol_outside_bound_plan")
        if not entry_window(now, self.calendar):
            return {"state": "unavailable", "current": False, "error": "outside_tail_entry_window", "message": failure_message("outside_tail_entry_window"), "assessment": None, "previous": None}
        if mode == "live" and (plan.market_session_date != now.date() or plan.generated_at > now):
            return {"state": "unavailable", "current": False, "error": "plan_session_mismatch", "message": failure_message("plan_session_mismatch"), "assessment": None, "previous": None}
        key = sha256(f"{plan_id}:{symbol}".encode()).hexdigest()[:24]
        try:
            with CrossProcessLock(self.store.path.with_name(f".entry-{key}.lock")):
                return self._assess(plan, candidate, scenario, now, mode, frame, benchmark, fetched_at, request_ms)
        except OperationBusy:
            return {**self.read(plan_id, symbol, scenario, now=now), "state": "refreshing", "current": False}

    def _assess(self, plan, candidate, scenario, now, mode, frame, benchmark, fetched_at, request_ms):
        started = monotonic()
        plan_id, symbol = plan.plan_id, candidate.symbol
        prior = self.store.entry_history(plan_id, symbol, scenario, limit=1, mode=mode, before=now)
        previous = prior[0] if prior else None
        attempt = self.store.entry_attempt(plan_id, symbol, scenario, mode=mode)
        if mode == "live" and attempt and timedelta(0) <= now - datetime.fromisoformat(attempt["attempted_at"]) < timedelta(seconds=REFRESH_SECONDS):
            return self.read(plan_id, symbol, scenario, now=now)
        if mode == "live" and previous and previous.mode == "live" and previous.evidence.cutoff == latest_closed_boundary(now):
            return self.read(plan_id, symbol, scenario, now=now)
        self.store.record_entry_attempt(plan_id, symbol, scenario, now, "refreshing", mode=mode)
        try:
            if self.market_runs.confirmed_suspension_at(symbol=symbol, now=now):
                raise ValueError("confirmed_suspension")
            benchmark_error = None
            cached = self.store.cached_entry_evidence(plan_id, symbol, now=now) if mode == "live" else None
            if cached and cached.cutoff == latest_closed_boundary(now):
                evidence = cached.model_copy(update={"request_ms": 0})
            elif mode == "live":
                if frame is not None:
                    raise ValueError("live_injected_data_forbidden")
                frame, fetched_at, request_ms = self.provider.fetch(symbol)
                try:
                    benchmark, _, benchmark_ms = self.provider.fetch("000300", index=True)
                    request_ms += benchmark_ms
                except (requests.RequestException, ValueError) as exc:
                    benchmark_error = f"{type(exc).__name__}:{exc}"
                evidence = build_evidence(frame, benchmark, candidate=candidate, now=now, fetched_at=fetched_at, request_ms=request_ms, benchmark_error=benchmark_error)
            elif frame is None or fetched_at is None:
                raise ValueError("historical_real_data_required")
            else:
                evidence = build_evidence(frame, benchmark, candidate=candidate, now=now, fetched_at=fetched_at, request_ms=request_ms, benchmark_error=benchmark_error)
            identity = sha256(f"{plan_id}:{symbol}:{scenario}:{mode}:{evidence.digest}".encode()).hexdigest()
            assessment_id = f"entry_{identity[:32]}"
            existing = self.store.entry_by_id(assessment_id)
            if existing:
                self.store.record_entry_attempt(plan_id, symbol, scenario, now, "ready", mode=mode)
                return self.read(plan_id, symbol, scenario, now=now) if mode == "live" else {"state": "historical", "current": False, "assessment": existing.model_dump(mode="json"), "previous": None, "error": None}
            # No question phrasing in canonical inference: same scenario/evidence
            # has exactly one result. Conversation interprets the user's context.
            context = {"scenario": scenario, "judgment_time": now.isoformat(), "evidence": evidence.model_dump(mode="json"),
                       "daily_candidate": candidate.model_dump(mode="json"), "previous": previous.model_dump(mode="json") if previous else None,
                       "historical_chain_only": mode == "historical" and (plan.market_session_date != now.date() or plan.generated_at > now)}
            prompt = """你是GP尾盘入场评估Agent。只基于给出的真实证据和原计划综合判断，输出JSON，严格符合schema。代码已计算数值，不计算新价格/指标，不改日线评分、排名和计划。判断最近15/30分钟和价格结构，区分全天涨而近期弱、跌后修复、持续走强、正常回踩、冲高回落、方向混合。不能以单个指标投票，不能制造尾盘分数。走势语义：strengthening需要近期持续抬升；repairing需要先弱后逐步修复；pullback需要近期先有明确向上结构，再发生未破坏结构的回踩。上下反复、近期缺少持续方向、15/30分钟证据分歧时用mixed或sideways并wait，不能因全天上涨或高于VWAP就称为正常回踩而给consider_entry。volume_recent_15m_to_prior_15m是相邻15分钟成交量比，不是市场量比，不代表异常放量。VWAP或基准缺失时说明局限，不把它当走弱。consider_entry只允许走势与原计划支持、entry_position=inside、未破止损、trade_constraints为空；弱则do_not_enter，走强但above也do_not_enter并说明不追，分歧则wait。add_position属于已有持仓加仓，缺少持仓规模/成本/风险预算，只能wait说明不能确认加仓，不伪装成首次建仓。理由引用 evidence_fields 中真实存在的非空字段；结论先行，理由简洁，不输出未提供的数值。change说明相对previous哪些新证据支持改变；没有上次记录则空字符串。日线action=watch是候选的日线观察属性，不是禁止入场；风险标记用于解释权衡，只有trade_constraints列出的明确交易事实才是硬约束。你必须独立综合近期走势，有真实支持且价位合适时可以明确consider_entry，不能因为watch永远wait。conclusion用一句用户语言直接给当前建议；reasons使用中文自然语言，不出现英文字段名或工程术语，不逐项抄指标。历史链路实验说明属于历史截断，仍判断该证据下的入场动作，但不得声称现场许可。"""
            schema = EntryJudgment.model_json_schema()
            allowed_fields = [key for key, value in evidence.model_dump().items() if value is not None]
            schema["properties"]["evidence_fields"]["items"] = {"type": "string", "enum": allowed_fields}
            response = self.model.chat([
                {"role": "system", "content": prompt + "\nevidence_fields只写字段本名，不加evidence.或下标，不能引用null或daily_candidate路径。\nschema=" + json.dumps(schema, ensure_ascii=False)},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ], temperature=0, json_mode=True, extra={"thinking": {"type": "disabled"}}, budget_stage="entry_assessment")
            judgment = EntryJudgment.model_validate_json(response["choices"][0]["message"]["content"])
            fields = evidence.model_dump()
            if any(field not in fields or fields[field] is None for field in judgment.evidence_fields):
                raise ValueError("entry_model_unbound_evidence:" + str([field for field in judgment.evidence_fields if field not in fields or fields[field] is None]))
            if judgment.action == "consider_entry" and (evidence.entry_position != "inside" or evidence.stop_breached or evidence.trade_constraints or scenario == "add_position" or judgment.trend in {"weakening", "mixed", "sideways", "unconfirmed"}):
                raise ValueError("entry_model_action_conflict")
            completed_at = now + timedelta(seconds=monotonic() - started) if mode == "live" else datetime.now(SHANGHAI)
            if mode == "live" and (not entry_window(completed_at, self.calendar) or not fresh(evidence.cutoff, completed_at)):
                raise ValueError("entry_expired_during_evaluation")
            result = EntryAssessment(assessment_id=assessment_id, plan_id=plan_id, symbol=symbol, scenario=scenario, assessed_at=now, completed_at=completed_at, mode=mode, evidence=evidence, judgment=judgment, previous_assessment_id=previous.assessment_id if previous else None, total_ms=(monotonic() - started) * 1000)
            result = self.store.commit_entry(result)
            self.store.record_entry_attempt(plan_id, symbol, scenario, now, "ready", mode=mode)
            return {"state": "ready" if mode == "live" else "historical", "current": mode == "live", "assessment": result.model_dump(mode="json"), "previous": previous.model_dump(mode="json") if previous else None, "error": None}
        except (requests.RequestException, ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
            # Failure is recorded as failure, never converted into an entry action.
            self.store.record_entry_attempt(plan_id, symbol, scenario, now, "unavailable", f"{type(exc).__name__}:{exc}", mode=mode)
            if mode == "historical":
                return {"state": "unavailable", "current": False, "assessment": None, "previous": None, "error": f"{type(exc).__name__}:{exc}"}
            return self.read(plan_id, symbol, scenario, now=now)
