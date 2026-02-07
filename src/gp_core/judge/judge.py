from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from gp_core.io import save_json, save_prompt, save_llm_raw
from gp_core.llm import LLMClient
from gp_core.schemas import ChampionDecision, MarketContext, StrategyRunResult


class Judge:
    def __init__(self, *, llm_cfg_path: str):
        self.llm = LLMClient(llm_cfg_path)

    def decide(self, run_dir: Path, *, A: MarketContext, runs: List[StrategyRunResult]) -> ChampionDecision:
        sys_prompt = (
            '你是策略裁判。仅返回 JSON：{strategy_id, name, reason}。\n'
            '综合市场背景与各策略 run 结果，给出冠军策略与裁决理由（包含权衡点）。不得多余文本。'
        )
        content = {
            'market_context': A.dict(),
            'candidates': [r.dict() for r in runs],
        }
        save_prompt(run_dir, '04', 'judge', {'model': self.llm.cfg.model, 'provider': self.llm.cfg.provider, 'messages': [{'role':'system','content':sys_prompt},{'role':'user','content':content}]})
        resp = self.llm.chat([
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': __import__('json').dumps(content, ensure_ascii=False)},
        ], json_response=True)
        save_llm_raw(run_dir, '04', 'judge', resp)
        txt = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
        data = __import__('json').loads(txt)
        dec = ChampionDecision(**data)
        save_json(run_dir / '04_champion.json', dec.dict())
        return dec

