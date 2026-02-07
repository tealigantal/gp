from __future__ import annotations

import argparse
from datetime import datetime, date
from pathlib import Path
from typing import List

import uvicorn

from .config import load_config
from .datapool import DataPool
from .features.core import compute_features_incremental
from .market_state import classify_env
from .report.render import render_markdown
from .report.schema import validate_report
from .serve import create_app
from .strategies.dsl import s1_rsi2_pullback
from .strategies.engine import scan_low_absorption
from .universe import Universe
from .utils import ensure_dir, save_json


def cmd_update(args):
    cfg = load_config()
    dp = DataPool(cfg)
    until = datetime.strptime(args.until, "%Y-%m-%d").date()
    uni = Universe(cfg)
    # Always update indices for environment classification
    dp.update_index_daily(until=until, lookback_days=max(120, args.lookback_days))
    codes = uni.candidate_codes_for(until)
    # If no explicit candidate pool, do nothing silently
    if not codes:
        dp.update_simple_breadth(until)
        print("No candidate pool found for", until, "(updated indices + breadth)")
        return
    batch = dp.update_bars_daily(codes, until=until, lookback_days=args.lookback_days)
    compute_features_incremental(dp, codes)
    dp.update_simple_breadth(until)
    print(f"Updated bars+features for {len(set(batch.get('code', [])))} codes up to {until}")


def cmd_run(args):
    cfg = load_config()
    dp = DataPool(cfg)
    d = datetime.strptime(args.date, "%Y-%m-%d").date()
    uni = Universe(cfg)
    codes = uni.candidate_codes_for(d)
    env = classify_env(dp, d)
    strat = s1_rsi2_pullback()
    hits = scan_low_absorption(dp, d, strat, env.env, codes)
    # Build report JSON
    top10 = []
    for h in hits:
        top10.append({
            "code": h.code,
            "indicators": h.features,
            "q_level": h.q_level,
            "chip_band": {"confidence": "low", "note": "近似模型占位"},
            "announcements": {"risk": "unknown", "note": "近30日公告增量抓取未实现或失败，需人工复核"},
            "actions": {
                "watch": "开盘后15分钟观察承接与量比，若承接改善且不临近压力带则允许入场",
                "manage": "持有期间若量能不配合或收盘跌破支撑带，减仓或出场；第3日时间止损",
            },
            "risk": {
                "invalidation": ["Gap>2%禁买", "贴近压力带禁买", "公告重大风险事件禁买"],
                "position": {"lot": 100, "risk_budget_pct": 0.8},
            },
        })
    report = {
        "date": d.strftime("%Y-%m-%d"),
        "tier": args.tier,
        "market_env": env.env,
        "main_themes": [],
        "candidate_pool_summary": {"count": len(codes), "window": "N/A"},
        "top10": top10,
        "champion": {"id": strat.id, "reason": "近期胜率与纪律约束较优"},
        "action_list": ["优先执行冠军策略", "严格两段盯盘", "Gap/压力带禁买", "时间止损第3日"],
        "disclaimer": cfg.raw["report"]["disclaimer"],
    }
    # Validate schema
    validate_report(report)
    # Render & save
    ensure_dir(cfg.results)
    json_path = cfg.results / f"report_{d.strftime('%Y%m%d')}.json"
    md_path = cfg.results / f"report_{d.strftime('%Y%m%d')}.md"
    save_json(json_path, report)
    save_json(cfg.results / "latest_report.json", report)
    md = render_markdown(report)
    md_path.write_text(md, encoding="utf-8")
    print("Saved:", json_path, "and", md_path)


def cmd_backtest(args):
    from .backtest.engine import backtest_daily_t1
    cfg = load_config()
    dp = DataPool(cfg)
    strat = s1_rsi2_pullback()  # Map id->dsl; demonstrate S1
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    # Codes from union of candidate pools in range (fallback: today's if missing)
    uni = Universe(cfg)
    codes = uni.candidate_codes_for(end)
    res = backtest_daily_t1(dp, strat, start, end, codes)
    run_dir = cfg.results / f"run_backtest_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
    ensure_dir(run_dir)
    res.trades.to_csv(run_dir / "trades.csv", index=False)
    save_json(run_dir / "metrics.json", res.metrics)
    print("Backtest metrics:", res.metrics)
    print("Trades saved to", run_dir / "trades.csv")


def cmd_serve(args):
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)


def main():
    p = argparse.ArgumentParser(prog="gp")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_update = sub.add_parser("update", help="增量更新数据池")
    p_update.add_argument("--until", required=True, help="YYYY-MM-DD")
    p_update.add_argument("--lookback-days", type=int, default=60)
    p_update.set_defaults(func=cmd_update)

    p_run = sub.add_parser("run", help="生成当日报告")
    p_run.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_run.add_argument("--tier", choices=["low","mid","high"], default="mid")
    p_run.set_defaults(func=cmd_run)

    p_bt = sub.add_parser("backtest", help="单策略回测")
    p_bt.add_argument("--strategy", required=True, help="策略ID，例如 S1")
    p_bt.add_argument("--start", required=True, help="YYYY-MM-DD")
    p_bt.add_argument("--end", required=True, help="YYYY-MM-DD")
    p_bt.set_defaults(func=cmd_backtest)

    p_srv = sub.add_parser("serve", help="启动 FastAPI 服务")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8000)
    p_srv.set_defaults(func=cmd_serve)

    # New: pipeline recommend
    def cmd_recommend(args):
        from gp_core.pipeline import Pipeline, PipelineConfig
        repo = Path('.')
        import json as _json
        profile = _json.loads(Path(args.profile).read_text(encoding='utf-8')) if args.profile else {'risk_level': 'neutral', 'topk': args.topk}
        date = args.date.replace('-', '')
        pipe = Pipeline(repo, llm_cfg='configs/llm.yaml', search_cfg='configs/search.yaml', strategies_cfg=str(repo / 'configs' / 'strategies.yaml'), cfg=PipelineConfig(lookback_days=args.lookback, topk=args.topk, queries=['A股 市场 两周 摘要','指数 成交额 情绪','板块 轮动 热点']))
        run_id, A, sel, runs, champ, resp = pipe.run(end_date=date, user_profile=profile, user_question=args.question or '', topk=args.topk)
        print('run_id:', run_id)
        txt = (Path('store') / 'pipeline_runs' / run_id / '05_final_response.txt').read_text(encoding='utf-8')
        print(txt)

    p_rec = sub.add_parser("recommend", help="Pipeline 推荐")
    p_rec.add_argument("--date", required=True, help="YYYYMMDD|YYYY-MM-DD")
    p_rec.add_argument("--question", default="")
    p_rec.add_argument("--profile", default=None, help="JSON file with UserProfile")
    p_rec.add_argument("--topk", type=int, default=3)
    p_rec.add_argument("--lookback", type=int, default=14)
    p_rec.set_defaults(func=cmd_recommend)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
