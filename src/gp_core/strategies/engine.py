from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from gp_core.io import save_json, save_prompt, save_llm_raw
from gp_core.llm import LLMClient
from gp_core.schemas import (
    MarketContext,
    StrategySelection,
    StrategyRunMetrics,
    StrategyRunResult,
)
from gp_core.strategies.registry import StrategyRegistry


def _load_configured_appcfg(repo_root: Path):
    from src.gpbt.config import AppConfig, Paths, Fees, UniverseCfg, BarsCfg, ExperimentCfg
    p = Path(repo_root) / 'configs' / 'config.yaml'
    if not p.exists():
        raise RuntimeError('configs/config.yaml missing (gpbt)')
    return AppConfig.load(str(p))


class StrategyEngine:
    def __init__(self, repo_root: Path, *, llm_cfg_path: str, registry: StrategyRegistry) -> None:
        self.repo_root = Path(repo_root)
        self.llm = LLMClient(llm_cfg_path)
        self.registry = registry

    def screen(self, run_dir: Path, *, A: MarketContext, user_profile: Dict[str, Any]) -> StrategySelection:
        # LLM-based selection (fail-fast)
        sys_prompt = (
            '你是策略筛选器。仅返回 JSON：{selected: [{strategy_id, reason}], rationale: str}。\n'
            '根据用户偏好（风险/风格/行业）与市场风格，从策略库中选择最合适的若干个。不得添加多余文本。'
        )
        content = {
            'user_profile': user_profile,
            'market_context': A.dict(),
            'registry': [s.dict() for s in self.registry.items],
        }
        save_prompt(run_dir, '02', 'select_strategies', {'model': self.llm.cfg.model, 'provider': self.llm.cfg.provider, 'messages': [{'role':'system','content':sys_prompt},{'role':'user','content':content}]})
        resp = self.llm.chat([
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': __import__('json').dumps(content, ensure_ascii=False)},
        ], json_response=True)
        save_llm_raw(run_dir, '02', 'select_strategies', resp)
        txt = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
        data = __import__('json').loads(txt)
        sel = StrategySelection(**data)
        save_json(run_dir / '02_selected_strategies.json', sel.dict())
        return sel

    def _rank_picks(self, date: str, strategy_id: str, topk: int) -> List[Dict[str, Any]]:
        from src.gpbt.rankers.llm_ranker import rank as llm_rank
        appcfg = _load_configured_appcfg(self.repo_root)
        df = llm_rank(appcfg, date, strategy_id, force=True, topk=topk)
        rows: List[Dict[str, Any]] = []
        for _, r in df.iterrows():
            rows.append({
                'trade_date': date,
                'rank': int(r.get('rank', 0) or 0),
                'ts_code': str(r.get('ts_code', '')),
                'score': float(r.get('score', 0.0) or 0.0),
                'confidence': float(r.get('confidence', 0.0) or 0.0),
                'reasons': str(r.get('reasons', '')),
                'risk_flags': str(r.get('risk_flags', '')),
            })
        return rows

    def _metrics_for(self, picks: List[Dict[str, Any]], date: str) -> StrategyRunMetrics:
        # Compute naive win_rate/avg_return from daily bars around date (proxy)
        from src.gpbt.storage import daily_bar_path, load_parquet
        rets: List[float] = []
        for p in picks:
            ts = str(p.get('ts_code'))
            df = load_parquet(daily_bar_path(self.repo_root / 'data', ts))
            if df.empty:
                continue
            ddf = df[df['trade_date'].astype(str) <= date].sort_values('trade_date')
            if len(ddf) >= 2:
                prev = float(ddf.iloc[-2]['close'])
                cur = float(ddf.iloc[-1]['close'])
                rets.append(cur / prev - 1.0)
        if not rets:
            return StrategyRunMetrics()
        wr = sum(1 for x in rets if x > 0) / len(rets)
        ar = sum(rets) / len(rets)
        return StrategyRunMetrics(win_rate=wr, avg_return=ar, max_drawdown=0.0, turnover=0.0, sample_period={'end': date})

    def run_one(self, run_dir: Path, *, strategy_id: str, date: str, topk: int, A: MarketContext) -> StrategyRunResult:
        spec = self.registry.by_id(strategy_id)
        picks = self._rank_picks(date, strategy_id, topk)
        metrics = self._metrics_for(picks, date)

        # LLM explanation and suggestions
        sys_prompt = (
            '你是策略解释器。仅返回 JSON：{rules_summary, signals[], suggestions{entry,stop_loss,take_profit,position}, llm_explanation}。\n'
            '结合市场背景，对该策略在当前周期的表现、适配性、信号触发条件与交易建议做解释。不得多余文本。'
        )
        content = {
            'strategy': spec.dict(),
            'market_context': A.dict(),
            'picks': picks,
            'metrics': metrics.dict(),
        }
        tag = f'run_{strategy_id}'
        save_prompt(run_dir, '03', tag, {'model': self.llm.cfg.model, 'provider': self.llm.cfg.provider, 'messages': [{'role':'system','content':sys_prompt},{'role':'user','content':content}]})
        resp = self.llm.chat([
            {'role': 'system', 'content': sys_prompt},
            {'role': 'user', 'content': __import__('json').dumps(content, ensure_ascii=False)},
        ], json_response=True)
        save_llm_raw(run_dir, '03', tag, resp)
        txt = resp.get('choices', [{}])[0].get('message', {}).get('content', '{}')
        explain = __import__('json').loads(txt)
        run = StrategyRunResult(
            provider='llm',
            strategy_id=spec.id,
            name=spec.name,
            tags=spec.tags,
            period={'start': date, 'end': date},
            metrics=metrics,
            rules_summary=explain.get('rules_summary',''),
            signals=list(explain.get('signals', [])),
            suggestions=explain.get('suggestions', {}),
            llm_explanation=explain.get('llm_explanation',''),
            picks=picks,
        )
        save_json(run_dir / '03_strategy_runs' / f'{spec.id}.json', run.dict())
        return run

