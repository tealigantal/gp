from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from gp_core.io import new_run_dir, save_json
from gp_core.llm import LLMClient
from gp_core.market_info import MarketInfo
from gp_core.schemas import (
    ChampionDecision,
    MarketContext,
    PipelineRunIndex,
    StrategyRunResult,
    StrategySelection,
)
from gp_core.strategies import StrategyEngine, StrategyRegistry
from gp_core.judge import Judge
from gp_core.qa import AnswerComposer


@dataclass
class PipelineConfig:
    lookback_days: int = 14
    topk: int = 3
    queries: List[str] = None  # type: ignore


class Pipeline:
    def __init__(self, repo_root: Path, *, llm_cfg: str, search_cfg: str, strategies_cfg: str, cfg: PipelineConfig | None = None) -> None:
        self.repo = Path(repo_root)
        self.llm_cfg = llm_cfg
        self.search_cfg = search_cfg
        self.strategies_cfg = strategies_cfg
        self.cfg = cfg or PipelineConfig(queries=["A股 市场 两周 摘要", "指数 成交额 情绪", "板块 轮动 热点"])

    def run(
        self,
        *,
        end_date: str,
        user_profile: Dict[str, Any],
        user_question: str,
        topk: int | None = None,
    ) -> Tuple[str, MarketContext, StrategySelection, List[StrategyRunResult], ChampionDecision, Dict[str, Any]]:
        # Setup run dir
        run_dir = new_run_dir(self.repo, end_date)
        run_id = run_dir.name
        # Step1: Market info
        mi = MarketInfo(self.repo, llm_cfg_path=self.llm_cfg, search_cfg_path=self.search_cfg)
        A, sources = mi.run(run_dir, end_date=end_date, lookback_days=self.cfg.lookback_days, queries=self.cfg.queries or [])
        # Step2: Screen strategies via LLM
        registry = StrategyRegistry.load(Path(self.strategies_cfg))
        se = StrategyEngine(self.repo, llm_cfg_path=self.llm_cfg, registry=registry)
        sel = se.screen(run_dir, A=A, user_profile=user_profile)
        # Step3: Run each strategy
        runs: List[StrategyRunResult] = []
        K = int(topk or self.cfg.topk)
        for it in sel.selected:
            sid = it.get('strategy_id')
            r = se.run_one(run_dir, strategy_id=sid, date=end_date, topk=K, A=A)
            runs.append(r)
        # Step4: LLM Judge
        judge = Judge(llm_cfg_path=self.llm_cfg)
        champion = judge.decide(run_dir, A=A, runs=runs)
        # Step5: Answer compose
        qa = AnswerComposer(llm_cfg_path=self.llm_cfg)
        resp, readable = qa.compose(run_dir, user_question=user_question, profile=user_profile, A=A, champion=champion, runs=runs, topk=K)
        # Index file
        artifacts = {
            '01_market_context': '01_market_context.json',
            '01_sources': '01_sources.jsonl',
            '02_selected_strategies': '02_selected_strategies.json',
            '03_dir': '03_strategy_runs/',
            '04_champion': '04_champion.json',
            '05_final_response_json': '05_final_response.json',
            '05_final_response_txt': '05_final_response.txt',
        }
        idx = PipelineRunIndex(run_id=run_id, end_date=end_date, created_at=datetime.utcnow().isoformat()+'Z', artifacts=artifacts)
        save_json(run_dir / 'index.json', idx.dict())
        return run_id, A, sel, runs, champion, resp.dict()

