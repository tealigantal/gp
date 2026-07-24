from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from uuid import uuid4

from ..contracts.publication import RecommendationPublication
from ..llm.client import LLMClient
from ..store import ContractStore


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
            else "官方公告批次未通过完整性校验，已整批保护性归零，基础评分与排序不受影响。"
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
        market_time_context = {
            "now": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
            "market_session_date": plan.market_session_date.isoformat() if plan else None,
            "daily_evidence_date": plan.daily_evidence_date.isoformat() if plan and plan.daily_evidence_date else None,
            "publication_created_at": publication.published_at.isoformat(),
            "runtime": {
                "observed_at": runtime.observed_at.isoformat(),
                "slot_closed_at": runtime.slot_closed_at.isoformat() if runtime.slot_closed_at else None,
                "market_phase": runtime.market_phase.value,
                "data_state": runtime.data_quality.state.value,
                "reason_codes": runtime.data_quality.reason_codes,
            } if runtime else None,
        }
        evidence = {
            "publication_id": publication.publication_id,
            "decision": publication.decision.model_dump(mode="json"),
            "lineage": publication.lineage.model_dump(mode="json"),
            "market_time_context": market_time_context,
            "Serenity产品说明": {
                "批次结论": serenity_summary,
                "本次实际权重": f"{(plan.serenity.applied_weight if plan else 0.0) * 100:.0f}%",
            },
            # Every candidate remains in scope, but only decision facts are
            # sent.  This keeps a full-market follow-up grounded without
            # spending context on internal feature vectors or duplicate data.
            "candidates": [
                {
                    "symbol": item.symbol,
                    "name": item.name,
                    "disposition": item.disposition.value,
                    "score": round(item.adaptive_score, 6),
                    "rank": item.ranking.rank,
                    "up_probability_3d": round(item.probability.probability, 6),
                    "risk_score": round(item.risk.score, 6),
                    "reason_codes": item.reason_codes,
                    "Serenity实际影响": serenity_effect(item),
                    "trade_plan": item.trade_plan.model_dump(mode="json") if item.disposition.value == "selected" else None,
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
6. publication.candidates[].risk_score 实际表示“风险调整分”，计算含义是 1 - 回撤概率，因此越高表示历史相似样本中的回撤概率越低、风险调整越有利，绝不能解释成“风险越高”。例如风险调整分为 0.724，表示对应回撤概率约为 0.276。它不是综合分，也不是执行风险。
7. reason_codes 是引擎已经确认的风险或筛选原因。只能解释实际提供的原因，不能自行补充基本面、波动率、新闻、资金流等未提供依据。
8. Serenity 是读取并核验上市公司官方公告的辅助维度，只作用于基础评分冻结后的 Top-30 候选。只有整个批次的候选覆盖、来源、分页、正文解析、时点和新鲜度都完整时，所有候选才统一启用固定 3% 权重；其归一化方向值在 -1 到 1，因此对综合分的实际影响最多为 -0.03 到 +0.03。完整但没有相关公告时方向值和实际贡献都是 0。任何一只候选信息不全、数据源失败、解析失败、过期或目标不匹配时，整个批次统一归零，基础分数、排序和荐股流程不受影响。Serenity 不是独立选股器，也不能覆盖基础引擎。

解释边界：
- 可以解释上述稳定的评分方法、权重、方向和入选规则。
- 解释某只候选时，只能引用传入 publication 中该候选实际提供的 score、rank、up_probability_3d、risk_score、reason_codes 和 trade_plan。
- 当前证据若没有提供执行质量、置信度或各分项贡献，不得倒推、重算或猜测该候选的具体分数组成；应明确说可以解释通用公式和已有数值，但本次发布没有提供完整分项归因。
- 解释 Serenity 时只能使用本次发布给出的实际状态、权重、贡献和原因。权重为 3% 但贡献为 0 表示完整批次中没有形成正负方向证据；权重为 0 表示整批保护性归零。不得猜测公告内容，也不得把 3% 说成上涨概率、收益率或固定加分。
- 不得把 risk_score 说成风险程度，不得把 score 或 risk_score 说成概率、收益率或百分比。
- 面向用户只讲候选范围、历史相似样本、概率校准、执行质量、回撤风险、综合分和入选档位等产品原理。不得输出或解释接口路径、数据库、表名、文件名、类名、内部对象名、内部标识、摘要值或工程链路；不得像接口报文一样复述字段名。
- 输入中的键名只用于传递事实。答复中禁止复述任何中英文字段名、英文状态枚举、原因代码、内部标签或类似报文的点号表达；必须把它们翻译成自然中文产品含义。即使用户询问技术细节，也只能解释产品原理和实际影响，不得展示 JSON、伪接口或内部代码。
- 仅基于传入的不可变发布事实作答；不能新增、删除或重排候选，不能编造数值、价格、股票名称、新闻或动作。

时间解释：必须先理解并自然说明当前市场时间。preopen 表示开盘前，计划通常基于前一交易日日线；morning 表示上午交易中；lunch 表示午休，应说明上午运行时数据截止时间并可继续解释已有计划，不能把午休说成交易时段；afternoon 表示下午交易中；closing_auction 表示收盘集合竞价；postclose 表示已收盘，应说明日线或下一交易日计划的实际状态。daily_evidence_date 是计划所依据的日线日期，runtime.observed_at 和 slot_closed_at 是最新运行时事实。若产品状态不可交易，必须明确说明，但仍要回答用户关于已有计划、评分和数据时间的问题。""",
                    },
                    {"role": "user", "content": __import__("json").dumps({"question": user_message, "publication": evidence}, ensure_ascii=False)},
                ],
                temperature=0.2,
                budget_stage="contract_narration",
            )
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"narration_unavailable:{type(exc).__name__}") from exc
        content = str((((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")).strip()
        if not content:
            raise ValueError("narration_empty")
        return content
