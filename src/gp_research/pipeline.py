from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .market_info import MarketInfo, MarketInfoConfig
from .schemas import MarketContext, StrategyRunResult, RecommendationResponse, save_json
from .strategy_engine import screen_strategies, run_strategy, judge_champion
from .qa import compose_response


@dataclass
class PipelineConfig:
    market_provider: str = "mock"  # web_search | emquant | manual | mock
    lookback_days: int = 14
    judge: str = "rule"  # rule | llm
    topk: int = 3


class RecommendPipeline:
    def __init__(self, repo_root: Path, *, llm_client=None, cfg: Optional[PipelineConfig] = None) -> None:
        self.repo_root = Path(repo_root)
        self.cfg = cfg or PipelineConfig()
        self.llm = llm_client
        # stores
        self.store_runs = self.repo_root / "store" / "pipeline_runs"
        self.store_runs.mkdir(parents=True, exist_ok=True)
        self.store_strat = self.repo_root / "store" / "strategy_runs"
        self.store_strat.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        *,
        end_date: Optional[str],
        user_profile: Dict[str, Any],
        user_question: str,
        topk: Optional[int] = None,
        market_provider: Optional[str] = None,
    ) -> Tuple[MarketContext, Dict[str, Any], List[StrategyRunResult], Dict[str, Any], RecommendationResponse]:
        # Step 0: resolve date
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        # Step1: Market info
        mi = MarketInfo(self.repo_root, cfg=MarketInfoConfig(provider=(market_provider or self.cfg.market_provider), lookback_days=self.cfg.lookback_days, keywords=[]))
        market_ctx = mi.get(end_date=end_date, lookback_days=self.cfg.lookback_days, provider=market_provider or self.cfg.market_provider)

        # Step2: Filter strategies
        style = (market_ctx.market_style_guess or {}).get("style")
        sel = screen_strategies(user_profile, market_style=style, use_llm=(self.cfg.judge == "llm"))
        selected = sel.to_dict()

        # Step3: Run each strategy
        run_results: List[StrategyRunResult] = []
        for it in selected["selected"]:
            sid = it["strategy_id"]
            run, picks = run_strategy(self.repo_root, sid, end_date, topk=int(topk or self.cfg.topk))
            run_results.append(run)
            # persist per-strategy run
            out_s = self.store_strat / f"{sid}_{end_date}.json"
            save_json(out_s, run.to_dict())

        # Step4: judge champion
        champion, why = judge_champion(style, run_results)
        champion_dict = {"id": champion.strategy_id, "name": champion.name, "reason": why}

        # Picks from champion
        picks = list(champion.picks)

        # Step5: QA compose final
        resp = compose_response(
            provider_hint=self.cfg.judge,
            llm_client=self.llm,
            user_question=user_question,
            user_profile=user_profile,
            market_summary=str((market_ctx.market_style_guess or {}).get("reason", "")) or "",
            champion={"name": champion.name, "reason": why},
            picks=picks,
            run_summaries=[r.to_dict() for r in run_results],
        )

        # Persist pipeline snapshot
        snap = {
            "end_date": end_date,
            "user_profile": user_profile,
            "market_context": market_ctx.to_dict(),
            "selected_strategies": selected,
            "run_results": [r.to_dict() for r in run_results],
            "champion": champion_dict,
            "response": resp.to_dict(),
        }
        out = self.store_runs / f"run_{end_date}.json"
        save_json(out, snap)
        return market_ctx, selected, run_results, champion_dict, resp

