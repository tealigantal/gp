from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from ..contracts.catalog import MarketPhase
from ..contracts.publication_policy import publication_ineligibility
from ..contracts.publication import RecommendationPublication
from ..llm.client import LLMClient
from ..store import ContractStore
from .market_runs import MarketRunStore
from .entry_service import EntryService
from pydantic import BaseModel, ConfigDict
from typing import Literal
from .market_phase import market_phase
from .target_resolver import resolve_plan_target
from .trading_calendar import CnATradingCalendar, load_cn_a_calendar


_SHANGHAI = ZoneInfo("Asia/Shanghai")
_PHASE_NAMES = {
    MarketPhase.PREOPEN: "开盘前",
    MarketPhase.MORNING: "上午交易中",
    MarketPhase.LUNCH: "午休",
    MarketPhase.AFTERNOON: "下午交易中",
    MarketPhase.CLOSING_AUCTION: "收盘集合竞价",
    MarketPhase.POSTCLOSE: "已收盘",
    MarketPhase.CLOSED: "休市",
}
_TRADING_PHASES = {MarketPhase.MORNING, MarketPhase.AFTERNOON, MarketPhase.CLOSING_AUCTION}
def project_current_market(*, plan_date, publication_tradeable: bool, now: datetime) -> dict[str, object]:
    """Project server-clock market truth without mutating a publication or runtime."""
    if now.tzinfo is None:
        raise ValueError("narration_clock_timezone_missing")
    answer_now = now.astimezone(_SHANGHAI)
    phase = market_phase(answer_now) if load_cn_a_calendar().is_open(answer_now.date()) else MarketPhase.CLOSED
    if plan_date is None:
        relation = "missing"
        executable = False
    elif plan_date < answer_now.date() or (plan_date == answer_now.date() and phase in {MarketPhase.POSTCLOSE, MarketPhase.CLOSED}):
        relation = "expired"
        executable = False
    elif plan_date > answer_now.date():
        relation = "future"
        executable = False
    elif phase is MarketPhase.PREOPEN:
        relation = "preopen"
        executable = False
    elif phase in _TRADING_PHASES:
        relation = "active"
        executable = bool(publication_tradeable)
    else:
        relation = "inactive"
        executable = False
    return {
        "observed_at": answer_now.isoformat(),
        "market_phase": phase.value,
        "market_phase_label": _PHASE_NAMES[phase],
        "plan_relation": relation,
        "tradeable_now": executable,
    }


def project_next_plan_target(*, plan, now: datetime, recovery_for_date: Callable[[str], dict[str, object]], calendar: CnATradingCalendar | None = None) -> dict[str, object]:
    """Project the separate plan-generation target; this never starts recovery work."""
    if now.tzinfo is None:
        raise ValueError("narration_clock_timezone_missing")
    answer_now = now.astimezone(_SHANGHAI)
    try:
        calendar = calendar or load_cn_a_calendar()
        is_open = calendar.is_open(answer_now.date())
        next_open = calendar.next_open_after(answer_now.date())
        target_session = answer_now.date() if is_open and answer_now.time() < time(15, 0) else next_open
        required_evidence = calendar.previous_open_before(target_session)
    except ValueError:
        return {
            "observed_at": answer_now.isoformat(),
            "market_session_date": None,
            "required_daily_evidence_date": None,
            "state": "unavailable",
            "completed": 0,
            "total": 0,
            "failed": 0,
            "next_retry_at": None,
            "approximate_universe": False,
        }

    required_date = required_evidence.isoformat()
    recovery = recovery_for_date(required_date)
    tracking_required = recovery.get("target_trade_date") == required_date
    recovery_state = str(recovery.get("state") or "unavailable")
    completed_daily_date = required_evidence if tracking_required and recovery_state == "ready" else None
    resolved = resolve_plan_target(
        now=answer_now,
        completed_daily_date=completed_daily_date,
        calendar=calendar.ref,
        is_open=is_open,
        next_open_session=next_open,
        required_daily_evidence_date=required_evidence,
    )
    published = bool(
        plan is not None
        and plan.market_session_date == resolved.market_session_date
        and plan.daily_evidence_date == required_evidence
        and publication_ineligibility(plan) is None
    )
    if published:
        state = "published"
    elif tracking_required and recovery_state == "ready":
        state = "ready_to_publish"
    elif recovery_state == "unavailable":
        state = "unavailable"
    else:
        state = "pending_daily_evidence"
    return {
        "observed_at": answer_now.isoformat(),
        "market_session_date": resolved.market_session_date.isoformat(),
        "required_daily_evidence_date": required_date,
        "state": state,
        "completed": int(recovery.get("completed") or 0) if tracking_required else 0,
        "total": int(recovery.get("total") or 0) if tracking_required else 0,
        "failed": int(recovery.get("failed") or 0) if tracking_required else 0,
        "next_retry_at": recovery.get("next_retry_at") if tracking_required else None,
        "approximate_universe": bool(recovery.get("approximate_universe")) if tracking_required else False,
    }


class ConversationService:
    """The one production narration path for immutable publication facts."""

    def __init__(
        self,
        store: ContractStore,
        narrator: LLMClient | None = None,
        *,
        now_provider: Callable[[], datetime] | None = None,
        market_runs: MarketRunStore | None = None,
        planning_calendar: CnATradingCalendar | None = None,
        entry_service: EntryService | None = None,
    ):
        self.store = store
        self.narrator = narrator or LLMClient()
        self.now_provider = now_provider or (lambda: datetime.now(_SHANGHAI))
        self.market_runs = market_runs or MarketRunStore()
        self.planning_calendar = planning_calendar
        self.entry_service = entry_service

    def reply(self, *, session_id: str | None, client_turn_id: str, user_message: str, publication_id: str | None = None) -> dict[str, object]:
        current = self.store.load_publication(publication_id) if publication_id else self.store.current_publication()
        if current is None:
            raise ValueError("publication_not_found")
        answer_now = self._now()
        active_session_id = session_id or f"session_{uuid4().hex}"
        publication = self.store.prepare_conversation(
            session_id=active_session_id,
            publication_id=current.publication_id,
            now=answer_now.astimezone(UTC),
        )
        existing = self.store.existing_reply(session_id=active_session_id, client_turn_id=client_turn_id)
        if existing is not None:
            return {
                "session_id": active_session_id,
                "client_turn_id": client_turn_id,
                "publication_id": publication.publication_id,
                "reply": existing,
                "publication": publication.model_dump(mode="json"),
            }
        history = self.store.read_conversation_session(active_session_id)[1]
        response = self._narrate(publication, user_message, now=answer_now, history=history)
        committed = self.store.commit_conversation_exchange(
            session_id=active_session_id,
            publication_id=publication.publication_id,
            client_turn_id=client_turn_id,
            user_turn_id=f"turn_{uuid4().hex}",
            user_message=user_message,
            assistant_turn_id=f"turn_{uuid4().hex}",
            assistant_message=response,
            now=answer_now.astimezone(UTC),
        )
        return {
            "session_id": active_session_id,
            "client_turn_id": client_turn_id,
            "publication_id": publication.publication_id,
            "reply": committed,
            "publication": publication.model_dump(mode="json"),
        }

    def _now(self) -> datetime:
        value = self.now_provider()
        if value.tzinfo is None:
            raise ValueError("narration_clock_timezone_missing")
        return value.astimezone(_SHANGHAI)

    def _temporal_truth(self, publication: RecommendationPublication, plan, runtime, *, now: datetime) -> dict[str, object]:
        plan_date = plan.market_session_date if plan else None
        current_market = project_current_market(
            plan_date=plan_date,
            publication_tradeable=publication.decision.tradeable_now,
            now=now,
        )
        relation = str(current_market["plan_relation"])
        phase_name = str(current_market["market_phase_label"])
        executable = bool(current_market["tradeable_now"])
        if relation == "missing":
            conclusion = "当前没有可供解释的完整计划。"
        elif relation == "expired":
            conclusion = (
                f"截至{now:%Y年%m月%d日 %H:%M}（上海时间），市场{phase_name}。"
                f"当前展示的计划交易日为{plan_date:%Y年%m月%d日}，该交易日已经结束；仅供回顾。"
            )
        elif relation == "future":
            conclusion = (
                f"截至{now:%Y年%m月%d日 %H:%M}（上海时间），市场{phase_name}。"
                f"当前展示的计划面向{plan_date:%Y年%m月%d日}，尚未进入该交易日；现在只能观察。"
            )
        elif relation == "preopen":
            conclusion = f"截至{now:%Y年%m月%d日 %H:%M}（上海时间），市场开盘前；当前计划面向今日，等待开盘后的运行时核验。"
        elif relation == "active":
            conclusion = (
                f"截至{now:%Y年%m月%d日 %H:%M}（上海时间），市场{phase_name}。"
                + ("当前计划的运行时核验允许执行。" if executable else "当前计划的运行时核验未允许执行，只能观察。")
            )
        else:
            conclusion = f"截至{now:%Y年%m月%d日 %H:%M}（上海时间），市场{phase_name}；当前不可执行。"

        next_target = project_next_plan_target(
            plan=plan, now=now, calendar=self.planning_calendar,
            recovery_for_date=lambda day: self.market_runs.health(initialize=False, trade_date=day),
        )
        target_date = next_target["market_session_date"]
        evidence_date = next_target["required_daily_evidence_date"]
        target_state = str(next_target["state"])
        if target_state == "published":
            next_summary = f"目标交易日{target_date}的计划已发布，日K证据截至{evidence_date}；当前等待该交易日开盘。"
        elif target_state == "ready_to_publish":
            next_summary = f"目标交易日{target_date}所需的{evidence_date}日K已完整核验，但新的计划版本尚未发布。"
        elif target_state == "pending_daily_evidence":
            if int(next_target["total"]):
                next_summary = (
                    f"目标交易日{target_date}的计划正在生成，需先补齐{evidence_date}日K；"
                    f"当前已完成{next_target['completed']}/{next_target['total']}，失败{next_target['failed']}，补齐后才会发布。"
                )
            else:
                next_summary = f"目标交易日{target_date}的计划需要{evidence_date}日K；市场日恢复尚未开始，不能据此宣称已有新的完整计划。"
        else:
            next_summary = "下一交易日计划状态暂不可确认，不能据此宣称已生成新的完整计划。"
        recovery = self.market_runs.health(initialize=False)
        historical_recovery = recovery if (
            recovery.get("state") not in {"ready", "not_started", "unavailable"}
            and recovery.get("target_trade_date")
            and str(recovery["target_trade_date"]) < str(evidence_date or "")
        ) else None
        conclusion = f"{conclusion}{next_summary}"

        runtime_truth = None
        if runtime is not None:
            runtime_truth = {
                "最后盘中观察时刻": runtime.observed_at.isoformat(),
                "最后盘中观察阶段": _PHASE_NAMES.get(runtime.market_phase, "未知阶段"),
                "最后盘中数据状态": runtime.data_quality.state.value,
                "说明": "这是绑定发布时的历史运行快照，不是回答时刻，不能据此描述当前市场阶段。",
            }
        return {
            "回答时刻": current_market["observed_at"],
            "当前市场阶段": phase_name,
            "当前是否可执行": executable,
            "计划时间关系": relation,
            "用户可见结论": conclusion,
            "计划交易日": plan_date.isoformat() if plan_date else None,
            "日线证据截止日": plan.daily_evidence_date.isoformat() if plan and plan.daily_evidence_date else None,
            "计划生成时刻": plan.generated_at.isoformat() if plan else None,
            "本次发布记录时刻": publication.published_at.isoformat(),
            "本次发布是否收盘后": publication.published_at.astimezone(_SHANGHAI).time().hour >= 15,
            "最后盘中观察": runtime_truth,
            "下一交易日计划": next_target,
            "历史日K回补": historical_recovery,
        }

    def _narrate(self, publication: RecommendationPublication, user_message: str, *, now: datetime, history=()) -> str:
        available, reason = self.narrator.available()
        if not available:
            raise ValueError(f"narration_unavailable:{reason}")
        plan = self.store.load_plan(publication.plan_id)
        runtime = self.store.load_runtime(publication.runtime_id) if publication.runtime_id else None
        temporal = self._temporal_truth(publication, plan, runtime, now=now)
        serenity_active = bool(plan and plan.serenity.applied_weight == 0.03)
        serenity_summary = "官方公告批次完整，固定启用3%辅助权重。" if serenity_active else "官方公告批次未通过完整性校验，已整批保护性归零，当前主排序分不受影响。"

        def serenity_effect(item) -> dict[str, object] | None:
            expert = next((value for value in item.experts if value.expert == "serenity"), None)
            if expert is None:
                return None
            if expert.weight == 0.0:
                explanation = "本批次保护性归零，对这只候选没有分数影响。"
            elif expert.contribution > 0:
                explanation = "已核验的官方公告证据形成正向辅助。"
            elif expert.contribution < 0:
                explanation = "已核验的官方公告证据形成负向辅助。"
            else:
                explanation = "批次完整，但没有形成相关的正负方向证据。"
            return {"实际权重": f"{expert.weight * 100:.0f}%", "综合分实际改变量": round(expert.contribution * 100, 4), "产品说明": explanation}

        def lunch_effect(item) -> dict[str, object] | None:
            expert = next((value for value in item.experts if value.expert == "intraday_5m"), None)
            if expert is None:
                return None
            observation_only = "lunch_observation_only" in expert.reason_codes
            return {
                "保留的综合分" if observation_only else "历史午盘排序分": round(float(item.adaptive_score) * 100, 4),
                "相对早盘综合分的实际改变量": round(expert.contribution * 100, 4),
                "产品说明": "午盘技术指标仅作附加观察，未重新估计盈亏证据，原总分及公告贡献保持不变。" if observation_only else "历史计划按当时午盘政策记录，未按新评分重算。",
            }

        def net_return_fact(item) -> str:
            net_return = item.probability.expected_net_return
            if net_return is None:
                return "该历史记录未保存净收益估计，无法判断其正负。"
            if net_return <= 0:
                return "估计净收益非正；相对排名靠前不代表正优势或可入场。"
            return "已记录的净收益估计为正；这不是实际成交收益或入场许可。"

        plan_status_names = {"recommend": "存在推荐候选", "no_recommend": "当前无推荐", "unavailable": "推荐不可用"}
        execution_status_names = {"available": "执行数据可用", "pending": "等待执行数据", "unavailable": "执行数据不可用"}
        disposition_names = {"selected": "优先观察", "reserve": "备选观察", "rejected": "未入选"}
        evidence = {
            "当前结论": {
                "推荐状态": plan_status_names.get(publication.decision.plan_status.value, "未知"),
                "执行数据状态": execution_status_names.get(publication.decision.execution_status.value, "未知"),
                "优先观察对象": [item.symbol for item in publication.candidates if item.disposition.value == "selected"],
            },
            "时间与执行事实": temporal,
            "Serenity产品说明": {"批次结论": serenity_summary, "本次实际权重": f"{(plan.serenity.applied_weight if plan else 0.0) * 100:.0f}%"},
            "候选列表": [
                {
                    "股票代码": item.symbol,
                    "股票名称": item.name,
                    "入选档位": disposition_names.get(item.disposition.value, "未知"),
                    "综合分": round(item.adaptive_score * 100, 4),
                    "评分口径": "总分为本计划生成时记录的相对评价，不是上涨概率或收益保证；不同评分政策的分数不能直接跨版本比较。",
                    "排序名次": item.ranking.rank,
                    "日线信号类型": item.signal.label,
                    "日线信号强度": round(item.signal.score, 6),
                    "未来三日上涨概率": round(item.probability.probability, 6),
                    "未来三日收益估计": f"{item.probability.expected_return_3d * 100:.4f}%" if item.probability.expected_return_3d is not None else None,
                    "往返成本假设": f"{item.probability.estimated_cost * 100:.4f}%" if item.probability.estimated_cost is not None else None,
                    "扣除成本后的收益估计": f"{item.probability.expected_net_return * 100:.4f}%" if item.probability.expected_net_return is not None else None,
                    "净收益风险事实": net_return_fact(item),
                    "风险调整分": round(item.risk.score, 6),
                    "Serenity实际影响": serenity_effect(item),
                    "午盘五分钟实际影响": lunch_effect(item),
                    "交易计划": {
                        "计划买入区间下沿": item.trade_plan.entry_low,
                        "计划买入区间上沿": item.trade_plan.entry_high,
                        "止损价": item.trade_plan.stop_price,
                        "止盈价": item.trade_plan.take_profit_prices,
                        "当前动作": item.trade_plan.action,
                    } if item.disposition.value == "selected" else None,
                }
                for item in publication.candidates
            ],
        }
        selected = [item for item in publication.candidates if item.disposition.value == "selected"]
        evidence["用户所见顺序"] = [item.symbol for item in selected]
        entry = self.entry_service or EntryService(self.store, model=self.narrator, calendar=self.planning_calendar)
        messages = [{"role": "system", "content": """你是GP对话Agent，中文、结论先行。真实会话历史和绑定计划是上下文；第一只、第二只始终指用户所见顺序，不能改成后来发布的计划。理解追问、继续、刷新、比较以及已有持仓。普通问候直接简短问候，不复述运行状态、不列推荐名单，不获取行情。需要当下入场判断必须调用evaluate_entry；已有持仓用add_position，首次用new_position。解释刚才变化调用read_entry，重新看一下调用evaluate_entry；同证据复用。不要猜价格、指标、时间，不更改原评分或排名，不根据关键词自行做结论。缺数据只能说本次未完成确认，绝不能解释为走弱/停牌/默认不买。失败不重试其他模型或模板。
调用evaluate_entry或read_entry后，本轮必须使用kind=entry引用工具结果，不能用information丢弃结果。所有最终回答通过respond工具：评估问题用kind=entry，引用本轮工具取得的symbol/scenario/action/assessment_id（未完成时action=unconfirmed、assessment_id=null）；当前建议由正式评估直接呈现；text必须为空；正式结论、理由与历史变化直接引用已保存评估，不再附加另一份自由建议。普通解释用kind=information，references为空，text简洁回答，不能用这种方式绕过当前入场评估。讨论历史判断须说明时间。分数已经是0到100，不能重新计算；历史记录没有的字段不可补零。不能补基本面、公告或行情事实。净收益非正与排名意义应如实解释。Serenity完整批次固定 3% 权重，不完整时整个批次统一归零。不能自行取总排序前三名替代已选名单。Serenity或午盘影响缺失不能据此断言整份计划采用旧评分。综合分不得再次换算，不同评分政策的分数不能直接跨版本比较。午盘技术指标仅作附加观察，不改写总分；午休市场门禁始终禁止交易。没有指定股票且上下文不明确时用information简短澄清，不抓全市场。read_plan可读绑定计划。"""},
                    {"role": "system", "content": json.dumps({"当前事实": evidence}, ensure_ascii=False)},
                    *[{"role": turn.role, "content": turn.content} for turn in history],
                    {"role": "user", "content": user_message}]
        tools = [
            _tool("read_plan", "读取本会话固定计划及用户所见股票顺序", {"type": "object", "properties": {}, "additionalProperties": False}),
            _tool("evaluate_entry", "获取或刷新一只股票的正式尾盘评估，自动复用有效证据；只处理相关股票", EntryToolArgs.model_json_schema()),
            _tool("read_entry", "读取同计划上一评估及前一评估，解释变化；不会下载行情", EntryToolArgs.model_json_schema()),
            _tool("respond", "最终回答；入场建议必须引用本轮实际工具结果", AgentAnswer.model_json_schema()),
        ]
        observed = {}
        history_requested = set()
        for _ in range(6):
            if observed:
                # Once evidence has been read, the final response schema must
                # bind it. Do not leave an unbound information escape hatch.
                bound_schema = AgentAnswer.model_json_schema()
                bound_schema["properties"]["kind"] = {"type": "string", "enum": ["entry"]}
                bound_schema["properties"]["references"]["minItems"] = 1
                bound_schema["properties"]["text"] = {"type": "string", "enum": [""]}
                tools[-1] = _tool("respond", "引用正式结果；text必须为空，正式理由和历史变化由已保存评估直接呈现。", bound_schema)
            message = self.narrator.run_chat_with_tools(messages, tools=tools, temperature=0, thinking={"type": "disabled"}, tool_choice="required", budget_stage="conversation_tools")
            calls = message["tool_calls"]
            if not calls or len(calls) > 3:
                raise ValueError("narration_tool_protocol_invalid")
            messages.append({k: v for k, v in message.items() if v is not None})
            for call in calls:
                name = call["function"]["name"]
                raw = call["function"]["arguments"]
                if name == "respond":
                    if len(calls) != 1:
                        raise ValueError("narration_final_tool_must_be_alone")
                    answer = AgentAnswer.model_validate_json(raw)
                    if answer.kind == "information":
                        if observed or answer.references or not answer.text.strip():
                            raise ValueError("narration_information_invalid")
                        return answer.text
                    if not answer.references:
                        raise ValueError("narration_entry_reference_required")
                    if answer.text:
                        raise ValueError("narration_entry_free_text_forbidden")
                    blocks = []
                    for ref in answer.references:
                        result = observed.get((ref.symbol, ref.scenario))
                        if result is None:
                            raise ValueError("narration_unobserved_entry")
                        if result["current"]:
                            from ..intraday.entry_evidence import fresh
                            from .entry_service import entry_window
                            clock = self._now()
                            if not entry_window(clock, entry.calendar) or not fresh(datetime.fromisoformat(result["assessment"]["evidence"]["cutoff"]), clock):
                                raise ValueError("entry_expired_during_response")
                        assessment = result["assessment"]
                        expected = assessment["judgment"]["action"] if result["current"] else "unconfirmed"
                        if ref.action != expected or ref.assessment_id != (assessment["assessment_id"] if result["current"] else None):
                            raise ValueError("narration_entry_action_conflict")
                        if not result["current"]:
                            blocks.append(f"{ref.symbol}：本次未完成当前行情与入场确认。" + ("正在刷新。" if result["state"] == "refreshing" else result["message"]))
                        else:
                            verdict = assessment["judgment"]
                            label = "加仓" if ref.scenario == "add_position" else "新建仓"
                            blocks.append(f"{ref.symbol}（{label}）：{verdict['conclusion']}\n" + "；".join(verdict["reasons"]) + (f"\n变化：{verdict['change']}" if verdict["change"] else "") + f"\n判断时间{assessment['assessed_at']}，五分钟走势截至{assessment['evidence']['cutoff']}。")
                        if (ref.symbol, ref.scenario) in history_requested:
                            historical = result["previous"] if result["current"] else assessment
                            if historical:
                                blocks.append(f"此前正式评估（{historical['assessed_at']}）：{historical['judgment']['conclusion']}\n{historical['judgment']['change']}")
                            elif not assessment:
                                blocks.append("没有此前正式评估可供比较，未完成确认不代表已经判定走弱。")
                    return "\n\n".join(blocks)
                if name == "read_plan":
                    if json.loads(raw) != {}:
                        raise ValueError("read_plan_arguments_invalid")
                    result = evidence
                elif name in {"evaluate_entry", "read_entry"}:
                    args = EntryToolArgs.model_validate_json(raw)
                    if args.symbol not in {c.symbol for c in publication.candidates}:
                        raise ValueError("entry_symbol_outside_bound_plan")
                    clock = self._now()
                    result = entry.assess(plan_id=plan.plan_id, symbol=args.symbol, scenario=args.scenario, now=clock) if name == "evaluate_entry" else entry.read(plan.plan_id, args.symbol, args.scenario, now=clock)
                    observed[(args.symbol, args.scenario)] = result
                    if name == "read_entry":
                        history_requested.add((args.symbol, args.scenario))
                else:
                    raise ValueError("narration_unknown_tool")
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result, ensure_ascii=False)})
        raise ValueError("narration_tool_budget_exceeded")


class EntryToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    scenario: Literal["new_position", "add_position"]


class EntryReference(EntryToolArgs):
    action: Literal["consider_entry", "do_not_enter", "wait", "unconfirmed"]
    assessment_id: str | None


class AgentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["information", "entry"]
    text: str
    references: list[EntryReference]


def _tool(name, description, parameters):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
