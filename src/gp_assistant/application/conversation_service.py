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
                    "trade_plan": item.trade_plan.model_dump(mode="json") if item.disposition.value == "selected" else None,
                }
                for item in publication.candidates
            ],
        }
        try:
            response = self.narrator.chat(
                [
                    {"role": "system", "content": "你是 GP 的中文荐股叙述层。仅基于传入的不可变 RecommendationPublication 和 market_time_context 作答；不能新增、删除或重排候选，不能编造数值、价格、新闻或动作。必须先理解并自然说明当前市场时间：preopen 表示开盘前，计划通常基于前一交易日日线；morning 表示上午交易中；lunch 表示午休，应说明上午运行时数据截止时间并可继续解释已有计划，不能把午休说成交易时段；afternoon 表示下午交易中；closing_auction 表示收盘集合竞价；postclose 表示已收盘，应说明日线或下一交易日计划的实际状态。daily_evidence_date 是计划所依据的日线日期，runtime.observed_at 和 slot_closed_at 是最新运行时事实。若产品状态不可交易，必须明确说明，但仍要回答用户关于已有计划和数据时间的问题。"},
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
