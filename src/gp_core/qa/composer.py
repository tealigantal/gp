from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from gp_core.io import save_json, save_text, save_prompt, save_llm_raw
from gp_core.llm import LLMClient
from gp_core.schemas import RecommendationItem, RecommendationResponse, MarketContext, ChampionDecision, StrategyRunResult


class AnswerComposer:
    def __init__(self, *, llm_cfg_path: str):
        self.llm = LLMClient(llm_cfg_path)

    def compose(
        self,
        run_dir: Path,
        *,
        user_question: str,
        profile: Dict[str, Any],
        A: MarketContext,
        champion: ChampionDecision,
        runs: List[StrategyRunResult],
        topk: int,
    ) -> Tuple[RecommendationResponse, str]:
        if not A.sources:
            raise RuntimeError('MarketContext missing sources; Step1 likely failed')
        sys_prompt = (
            '你是投研答复助手。只返回 JSON，不要多余文字。字段：'
            '{provider, summary, chosen_strategy{name,reason}, recommendations[], risks[], assumptions[], evidence[] }。'
            'recommendations 每项包含 code/name?/direction/thesis/entry/stop_loss/take_profit/position_sizing。'
            'evidence 用 URL 列表引用来源。请使用简体中文。'
        )
        content = {
            'question': user_question,
            'profile': profile,
            'market_context': A.dict(),
            'champion': champion.dict(),
            'runs': [r.dict() for r in runs],
            'topk': topk,
        }
        save_prompt(run_dir, '05', 'answer', {'model': self.llm.cfg.model, 'provider': self.llm.cfg.provider, 'messages': [{'role':'system','content':sys_prompt},{'role':'user','content':content}]})
        resp = self.llm.chat([
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': __import__('json').dumps(content, ensure_ascii=False)},
        ], json_response=True)
        save_llm_raw(run_dir, '05', 'answer', resp)
        txt = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
        data = __import__('json').loads(txt)
        out = RecommendationResponse(**data)
        save_json(run_dir / '05_final_response.json', out.dict())
        readable = self._to_text(out)
        save_text(run_dir / '05_final_response.txt', readable)
        return out, readable

    def _to_text(self, resp: RecommendationResponse) -> str:
        lines: List[str] = []
        lines.append(f"市场摘要：{resp.summary}")
        cs = resp.chosen_strategy or {}
        lines.append(f"冠军策略：{cs.get('name','?')}｜{cs.get('reason','')}")
        lines.append("推荐标的：")
        for i, it in enumerate(resp.recommendations, start=1):
            lines.append(f"{i}. {it.code} {it.name or ''}｜{it.direction}｜{it.thesis}")
            if it.entry or it.stop_loss or it.take_profit:
                lines.append(f"   入场:{it.entry or '-'} 止损:{it.stop_loss or '-'} 止盈:{it.take_profit or '-'} 仓位:{it.position_sizing or '-'}")
        if resp.risks:
            lines.append("风险提示：" + '；'.join(resp.risks))
        return '\n'.join(lines)
