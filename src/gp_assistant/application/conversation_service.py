from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from uuid import uuid4

from ..contracts.publication import RecommendationPublication
from ..llm.client import LLMClient
from ..store import ContractStore
from .market_runs import MarketRunStore


class ConversationService:
    def __init__(self, store: ContractStore, narrator: LLMClient | None = None):
        self.store = store
        self.narrator = narrator or LLMClient()

    def reply(self, *, session_id: str | None, client_turn_id: str, user_message: str) -> dict[str, object]:
        current = self.store.current_publication()
        if current is None:
            raise ValueError("publication_not_found")
        now = datetime.now(UTC)
        active_session_id = session_id or f"session_{uuid4().hex}"
        publication = self.store.prepare_conversation(session_id=active_session_id, publication_id=current.publication_id, now=now)
        existing = self.store.existing_reply(session_id=active_session_id, client_turn_id=client_turn_id)
        if existing is not None:
            return {"session_id": active_session_id, "client_turn_id": client_turn_id, "publication_id": publication.publication_id, "reply": existing, "publication": publication.model_dump(mode="json")}
        response = self._narrate(publication, user_message)
        committed = self.store.commit_conversation_exchange(
            session_id=active_session_id,
            publication_id=publication.publication_id,
            client_turn_id=client_turn_id,
            user_turn_id=f"turn_{uuid4().hex}",
            user_message=user_message,
            assistant_turn_id=f"turn_{uuid4().hex}",
            assistant_message=response,
            now=datetime.now(UTC),
        )
        return {"session_id": active_session_id, "client_turn_id": client_turn_id, "publication_id": publication.publication_id, "reply": committed, "publication": publication.model_dump(mode="json")}

    def _narrate(self, publication: RecommendationPublication, user_message: str) -> str:
        available, reason = self.narrator.available()
        if not available:
            raise ValueError(f"narration_unavailable:{reason}")
        plan = self.store.load_plan(publication.plan_id)
        runtime = self.store.load_runtime(publication.runtime_id) if publication.runtime_id else None
        serenity_active = bool(plan and plan.serenity.applied_weight == 0.03)
        serenity_summary = (
            "官方公告批次完整，固定启用3%辅助权重。"
            if serenity_active
            else "官方公告批次未通过完整性校验，已整批保护性归零，当前主排序分不受影响。"
        )

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
                "产品说明": "上午闭合五分钟数据已直接参与冻结候选范围内的午盘重排；最终排序分已经包含本批次实际生效的 Serenity 影响。",
            }
        phase_names = {
            "preopen": "开盘前",
            "morning": "上午交易中",
            "lunch": "午休",
            "afternoon": "下午交易中",
            "closing_auction": "收盘集合竞价",
            "postclose": "已收盘",
            "closed": "休市",
        }
        state_names = {"ready": "数据完整", "stale": "数据过期", "unavailable": "数据不可用"}
        recovery = MarketRunStore().health()
        market_time_context = {
            "当前上海时间": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "计划交易日": plan.market_session_date.isoformat() if plan else None,
            "日线证据截止日": plan.daily_evidence_date.isoformat() if plan and plan.daily_evidence_date else None,
            "本次结果发布时间": publication.published_at.isoformat(),
            "运行时状态": {
                "观察时间": runtime.observed_at.isoformat(),
                "数据截止时间": runtime.slot_closed_at.isoformat() if runtime.slot_closed_at else None,
                "市场阶段": phase_names.get(runtime.market_phase.value, "未知阶段"),
                "数据状态": state_names.get(runtime.data_quality.state.value, "未知状态"),
            } if runtime else None,
            "市场数据恢复": (
                "恢复中，当前对话继续绑定最近一份完整发布；恢复任务不会生成新的不完整推荐。"
                if recovery.get("state") != "ready" else "无待恢复市场数据。"
            ),
        }
        plan_status_names = {"recommend": "存在推荐候选", "no_recommend": "当前无推荐", "unavailable": "推荐不可用"}
        execution_status_names = {"available": "执行数据可用", "pending": "等待执行数据", "unavailable": "执行数据不可用"}
        disposition_names = {"selected": "入选", "reserve": "备选", "rejected": "未入选"}
        evidence = {
            "当前结论": {
                "推荐状态": plan_status_names.get(publication.decision.plan_status.value, "未知"),
                "执行数据状态": execution_status_names.get(publication.decision.execution_status.value, "未知"),
                "现在是否可交易": publication.decision.tradeable_now,
            },
            "市场时间": market_time_context,
            "Serenity产品说明": {
                "批次结论": serenity_summary,
                "本次实际权重": f"{(plan.serenity.applied_weight if plan else 0.0) * 100:.0f}%",
            },
            # Every candidate remains in scope, but only decision facts are
            # sent.  This keeps a full-market follow-up grounded without
            # spending context on internal feature vectors or duplicate data.
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
        try:
            response = self.narrator.chat(
                [
                    {
                        "role": "system",
                        "content": """你是 GP 的中文荐股叙述层。你只负责解释算法引擎已经确定的候选、排名、分数和计划，不参与选股、计算、重排或修改结论。

评分引擎的产品原理如下，用户询问“怎么评分”“为什么入选”“分数代表什么”时，要用自然中文准确解释：
1. 引擎先检查完整的 A 股主板候选范围，剔除 ST 和退市标的；日线覆盖达到完整性要求后，按流动性选取最多 200 只进入精细评分。
2. 每只候选先识别当前日线形态，再从当时已经成熟、不会使用未来结果的历史相似情形中取最多 80 个近邻样本。历史基准由全局样本、同类信号样本和同市场状态样本按 50%、30%、20% 混合，再与近邻样本的相似度加权结果收缩校准，得到未来 3 日上涨概率、回撤概率、置信度和不确定性。置信度主要取决于有效样本量和平均相似度。
3. 执行质量分 = 35% 回踩质量 + 25% 量能确认 + 20% 流动性 + 20% 概率置信度。它衡量当前形态是否便于执行，不等同于上涨概率。
4. 综合分 = 50% 三日上涨概率 + 30% 执行质量 + 20% 概率置信度 - 20% 回撤概率，最终限制在 0 到 1。综合分是排序依据，不是上涨概率，也不是收益率。
5. 候选按综合分从高到低排序；综合分达到 0.5 的候选可进入 selected，但最多选 3 只；0.4 到 0.5 为 reserve；低于 0.4 为 rejected。名额限制意味着分数超过 0.5 也可能因为排在前三名之外而成为 reserve。
6. 提供给你的“风险调整分”含义是 1 - 回撤概率，因此越高表示历史相似样本中的回撤概率越低、风险调整越有利，绝不能解释成“风险越高”。例如风险调整分为 0.724，表示对应回撤概率约为 0.276。它不是综合分，也不是执行风险。
7. 只能解释实际提供的候选事实，不能自行补充基本面、波动率、新闻、资金流等未提供依据。
8. Serenity 是读取并核验上市公司官方公告的辅助维度，只作用于基础评分冻结后的 Top-30 候选。只有整个批次的候选覆盖、来源、分页、正文解析、时点和新鲜度都完整时，所有候选才统一启用固定 3% 权重；其归一化方向值在 -1 到 1，因此对综合分的实际影响最多为 -0.03 到 +0.03。完整但没有相关公告时方向值和实际贡献都是 0。任何一只候选信息不全、数据源失败、解析失败、过期或目标不匹配时，整个批次统一归零，基础分数、排序和荐股流程不受影响。Serenity 不是独立选股器，也不能覆盖基础引擎。
9. 午盘重排不重新扫描全市场。早盘日线计划先冻结 Top-30 和原有交易事实；11:30 后，只有这30只股票以及沪深300都具备同一交易日从09:35到11:30的24根完整闭合五分钟线，系统才创建一个新的午盘计划版本。午盘信号分由四部分组成：45% 是股票上午涨跌相对沪深300的强弱，30% 是收盘价相对上午成交量加权价格代理的位置，15% 是收盘价位于上午最高价和最低价区间的位置，10% 是最后一小时涨跌；各分项按固定合理区间限制到0至1，再相加得到午盘排序分。随后只叠加本批次实际生效的 Serenity 贡献，仍受正负0.03限制。午盘计划直接按这个新鲜分数在冻结 Top-30 内重排，早盘计划和日线事实不会被覆盖或改写。任何一只股票、指数、时点或数值不完整时都不产生午盘计划，继续保留早盘结果。午休市场门禁始终禁止交易；重排只更新研究顺序，不代表午休可以买入。

解释边界：
- 可以解释上述稳定的评分方法、权重、方向和入选规则。
- 解释某只候选时，只能引用传入事实中的综合分、排序名次、未来三日上涨概率、风险调整分和交易计划。
- 当前证据若没有提供执行质量、置信度或各分项贡献，不得倒推、重算或猜测该候选的具体分数组成；应明确说可以解释通用公式和已有数值，但本次发布没有提供完整分项归因。
- 解释 Serenity 时只能使用本次发布给出的实际状态、权重、贡献和原因。权重为 3% 但贡献为 0 表示完整批次中没有形成正负方向证据；权重为 0 表示整批保护性归零。不得猜测公告内容，也不得把 3% 说成上涨概率、收益率或固定加分。
- 解释午盘重排时，只能使用本次发布给出的午盘最终排序分、实际改变量、最终排名和截止时间。最终排序分已经包含本批次实际生效的 Serenity 影响；可以解释上述固定四部分原理，但不得倒推截断前的五分钟原始分，也不得根据价格自行重算或把最终排序分说成上涨概率、收益率。没有午盘实际影响时，应说明当前仍是早盘计划，不能假称已经重排。
- 不得把风险调整分说成风险程度，不得把综合分或风险调整分说成概率、收益率或百分比。
- 面向用户只讲候选范围、历史相似样本、概率校准、执行质量、回撤风险、综合分和入选档位等产品原理。不得输出或解释接口路径、数据库、表名、文件名、类名、内部对象名、内部标识、摘要值或工程链路；不得像接口报文一样复述字段名。
- 输入中的键名只用于传递事实。答复中禁止复述任何中英文字段名、英文状态枚举、原因代码、内部标签或类似报文的点号表达；必须把它们翻译成自然中文产品含义。即使用户询问技术细节，也只能解释产品原理和实际影响，不得展示 JSON、伪接口或内部代码。
- 仅基于传入的不可变发布事实作答；不能新增、删除或重排候选，不能编造数值、价格、股票名称、新闻或动作。

时间解释：必须先理解并自然说明当前市场时间。开盘前的计划通常基于前一交易日日线；上午和下午交易中可以说明最新运行状态；午休应说明上午数据截止时间，不能把午休说成交易时段；收盘集合竞价和已收盘状态也必须按实际时间说明。输入中的日线证据截止日、观察时间和数据截止时间是唯一可用的时间事实。若产品状态不可交易，必须明确说明，但仍要回答用户关于已有计划、评分和数据时间的问题。""",
                    },
                    {"role": "user", "content": __import__("json").dumps({"用户问题": user_message, "当前事实": evidence}, ensure_ascii=False)},
                ],
                temperature=0.2,
                budget_stage="contract_narration",
            )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"narration_unavailable:{type(exc).__name__}") from exc
        content = str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
        if not content:
            raise ValueError("narration_empty")
        forbidden_internal_details = (
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
        lowered = content.casefold()
        if any(detail in lowered for detail in forbidden_internal_details):
            raise ValueError("narration_unsafe_internal_detail")
        return content
