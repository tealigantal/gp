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
from .runtime_producer import market_phase
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
_FORBIDDEN_INTERNAL_DETAILS = (
    "publication_id",
    "plan_id",
    "runtime_id",
    "source_digest",
    "lookup_digest",
    "recommendation_plans",
    "runtime_observations",
    "recommendation_publications",
    "contractstore",
    "recommendationplan",
    "runtimeobservation",
    "recommendationpublication",
    "lunch_5m_producer",
    "intraday_5m",
    "serenity_batch",
    "reason_codes",
    "batch_digest",
    "contract_store",
    "/api/",
    "sqlite",
    ".db",
    ".py",
    "```",
    "{\"",
    "select ",
    "insert ",
    "delete from ",
    "http://",
    "https://",
    "数据库表",
    "接口路径",
    "字段名",
)


def project_current_market(*, plan_date, publication_tradeable: bool, now: datetime) -> dict[str, object]:
    """Project server-clock market truth without mutating a publication or runtime."""
    if now.tzinfo is None:
        raise ValueError("narration_clock_timezone_missing")
    answer_now = now.astimezone(_SHANGHAI)
    phase = market_phase(answer_now)
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


def project_next_plan_target(*, plan, now: datetime, recovery: dict[str, object], calendar: CnATradingCalendar | None = None) -> dict[str, object]:
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
    ):
        self.store = store
        self.narrator = narrator or LLMClient()
        self.now_provider = now_provider or (lambda: datetime.now(_SHANGHAI))
        self.market_runs = market_runs or MarketRunStore()
        self.planning_calendar = planning_calendar

    def reply(self, *, session_id: str | None, client_turn_id: str, user_message: str) -> dict[str, object]:
        current = self.store.current_publication()
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
        response = self._narrate(publication, user_message, now=answer_now)
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

        recovery = self.market_runs.health(initialize=False)
        next_target = project_next_plan_target(plan=plan, now=now, recovery=recovery, calendar=self.planning_calendar)
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
        }

    def _narrate(self, publication: RecommendationPublication, user_message: str, *, now: datetime) -> str:
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
            return {"实际权重": f"{expert.weight * 100:.0f}%", "综合分实际改变量": round(expert.contribution, 6), "产品说明": explanation}

        def lunch_effect(item) -> dict[str, object] | None:
            expert = next((value for value in item.experts if value.expert == "intraday_5m"), None)
            if expert is None:
                return None
            return {
                "午盘最终排序分": round(float(item.adaptive_score), 6),
                "相对早盘综合分的实际改变量": round(expert.contribution, 6),
                "产品说明": "上午闭合五分钟数据已直接参与冻结候选范围内的午盘重排。",
            }

        plan_status_names = {"recommend": "存在推荐候选", "no_recommend": "当前无推荐", "unavailable": "推荐不可用"}
        execution_status_names = {"available": "执行数据可用", "pending": "等待执行数据", "unavailable": "执行数据不可用"}
        disposition_names = {"selected": "入选", "reserve": "备选", "rejected": "未入选"}
        evidence = {
            "当前结论": {
                "推荐状态": plan_status_names.get(publication.decision.plan_status.value, "未知"),
                "执行数据状态": execution_status_names.get(publication.decision.execution_status.value, "未知"),
            },
            "时间与执行事实": temporal,
            "Serenity产品说明": {"批次结论": serenity_summary, "本次实际权重": f"{(plan.serenity.applied_weight if plan else 0.0) * 100:.0f}%"},
            "候选列表": [
                {
                    "股票代码": item.symbol,
                    "股票名称": item.name,
                    "入选档位": disposition_names.get(item.disposition.value, "未知"),
                    "综合分": round(item.adaptive_score, 6),
                    "排序名次": item.ranking.rank,
                    "未来三日上涨概率": round(item.probability.probability, 6),
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
        messages = [
            {
                "role": "system",
                "content": """你是 GP 的唯一中文荐股叙述层。你只解释算法引擎已经确定的候选、排名、分数和交易计划；不能选股、重排、计算或改写结论。

时间与执行边界：输入的“时间与执行事实”由程序确定且优先级最高。程序会把其中的“用户可见结论”单独展示在你的回答前。你的正文不得再判断、复述或推断当前时间、当前市场阶段、当前是否可执行、计划是否已经结束、是否属于下一交易日，尤其不能把“最后盘中观察”写成回答时刻，也不能把发布记录时刻写成日线计划生成时刻。若需要提日期，只能明确区分“日线证据截止日”和“计划交易日”；不能把它们称为同一个“今天”。

事实边界：只能解释输入候选中的综合分、排序、未来三日上涨概率、风险调整分、Serenity 实际影响和交易计划。综合分是排序依据，不是上涨概率或收益率；风险调整分为一减回撤概率，越高表示历史回撤概率越低。不得补充基本面、新闻、资金流、公告内容或任何未提供的价格、日期、数值。候选之外不得新增、删除或重排标的。

Serenity：它只作用于基础评分冻结后的 Top-30。完整批次固定 3% 权重；贡献为0表示没有正负方向证据，权重为0表示整个批次统一归零。不得猜测公告内容，不能把权重、贡献或综合分说成上涨概率。

午盘重排：午盘不会重新扫描全市场。早盘先冻结 Top-30 与交易事实；11:30 后，只有这30只股票及沪深300都具备同一交易日09:35到11:30的24根完整闭合五分钟线，才创建午盘计划。午盘排序分的45% 是股票上午涨跌相对沪深300的强弱，30%是收盘价相对上午成交量加权价格代理的位置，15%是收盘价位于上午最高低区间的位置，10%是最后一小时涨跌；随后仅叠加本批次实际生效的 Serenity 贡献。午休市场门禁始终禁止交易；缺任何一只股票、指数、时点或数值时保留早盘计划，不能假称已经重排。

表达：先回答用户问题，再逐只说明相关候选。不要输出表格、JSON、接口、数据库、类名、字段名、原因代码或工程实现。每只候选的数值必须绑定该候选的输入事实；无候选时只解释等待条件，不得补充替代股票。""",
            },
            {"role": "user", "content": json.dumps({"用户问题": user_message, "当前事实": evidence}, ensure_ascii=False)},
        ]
        content = self._chat(messages, stage="contract_narration")
        content = self._remove_duplicate_temporal_notice(content, str(temporal["用户可见结论"]))
        violation = self._narration_violation(content, temporal)
        if violation is not None:
            repair_messages = [
                *messages,
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"上一份草稿违反时间叙述契约：{violation}。请只根据原始事实重写正文；不要写当前时间、市场阶段、可执行性、计划时态或发布时态。"},
            ]
            content = self._chat(repair_messages, stage="contract_narration_repair")
            content = self._remove_duplicate_temporal_notice(content, str(temporal["用户可见结论"]))
            violation = self._narration_violation(content, temporal)
            if violation is not None:
                raise ValueError(violation)
        if not content:
            raise ValueError("narration_empty")
        return f"{temporal['用户可见结论']}\n\n{content}"

    def _chat(self, messages: list[dict[str, str]], *, stage: str) -> str:
        try:
            response = self.narrator.chat(messages, temperature=0.0, budget_stage=stage)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"narration_unavailable:{type(exc).__name__}") from exc
        content = str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
        if not content:
            raise ValueError("narration_empty")
        return content

    @staticmethod
    def _remove_duplicate_temporal_notice(content: str, notice: str) -> str:
        """The deterministic notice is already rendered by this service, never by the LLM."""
        return content.replace(notice, "").strip()

    @staticmethod
    def _narration_violation(content: str, temporal: dict[str, object]) -> str | None:
        lowered = content.casefold()
        if any(detail in lowered for detail in _FORBIDDEN_INTERNAL_DETAILS):
            return "narration_unsafe_internal_detail"
        if "当前时间是" in content or "当前上海时间是" in content:
            return "narration_current_time_restatement"
        if temporal["当前市场阶段"] != "收盘集合竞价" and ("当前市场处于收盘集合竞价" in content or "当前处于收盘集合竞价" in content):
            return "narration_stale_runtime_phase"
        if temporal["本次发布是否收盘后"] is False and "收盘后发布" in content:
            return "narration_false_postclose_publication"
        if temporal["计划时间关系"] == "expired" and any(phrase in content for phrase in ("供明日开盘", "明日开盘后参考", "下一交易日参考", "明天开盘参考")):
            return "narration_expired_plan_as_next_session"
        if temporal["当前是否可执行"] is False and any(phrase in content for phrase in ("现在可以买", "当前可执行", "可以立即买入", "已触发买入")):
            return "narration_execution_state_conflict"
        return None
