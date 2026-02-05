from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd
from loguru import logger

from .config import AppConfig
from .providers.base import DataProvider
from .providers.tushare_provider import TushareProvider
from .providers.akshare_provider import AkShareProvider
from .providers.eastmoney_curl_provider import EastMoneyCurlProvider
from .providers.local_files_provider import LocalFilesProvider
from .storage import save_parquet, load_parquet, raw_path, daily_bar_path, min5_bar_path
from .universe import build_universe, select_top_k
from .engine.backtest import BacktestEngine
from .doctor import run_doctor
from .rankers.llm_ranker import rank as llm_rank
from .policy.policy_store import PolicyStore
from .tuner.policy_tuner import tune as tune_policy


def get_provider(name: str) -> DataProvider:
    if name == 'tushare':
        return TushareProvider()
    if name == 'akshare':
        return AkShareProvider()
    if name == 'eastmoney_curl' or name == 'eastmoney':
        return EastMoneyCurlProvider()
    if name == 'local_files':
        return LocalFilesProvider()
    raise ValueError(f"Unknown provider: {name}")


def cmd_init(cfg: AppConfig) -> None:
    cfg.ensure_dirs()
    logger.success("Initialized directories under {}", cfg.paths)


def cmd_fetch(cfg: AppConfig, start: str, end: str, *, max_codes: int | None = None, no_minutes: bool = False, max_days: int | None = None, retries: int = 0, min_provider: str | None = None, codes: list[str] | None = None) -> None:
    cfg.ensure_dirs()
    prov = get_provider(cfg.provider)

    # Stock basic
    # stock_basic may be unavailable for some providers; allow specifying codes directly
    if codes is None:
        sb = prov.get_stock_basic()
        save_parquet(sb, raw_path(cfg.paths.data_root, 'stock_basic.parquet'))
        logger.info("Saved stock_basic: {} rows", len(sb))
        codes = sb['ts_code'].dropna().astype(str).unique().tolist()
    else:
        # persist as a minimal stock_basic for downstream
        import pandas as pd
        sb = pd.DataFrame({'ts_code': codes, 'symbol': [c.split('.')[0] for c in codes], 'name': ['']*len(codes), 'exchange': ['']*len(codes), 'market': ['涓绘澘']*len(codes), 'list_date': ['']*len(codes), 'delist_date': ['']*len(codes)})
        save_parquet(sb, raw_path(cfg.paths.data_root, 'stock_basic.parquet'))

    # Name change
    nc = prov.get_namechange(None)
    save_parquet(nc, raw_path(cfg.paths.data_root, 'namechange.parquet'))
    logger.info("Saved namechange: {} rows", len(nc))

    # Trade calendar
    cal = prov.get_trade_calendar(start, end)
    save_parquet(cal, raw_path(cfg.paths.data_root, 'trade_cal.parquet'))
    logger.info("Saved trade_cal: {} rows", len(cal))

    # Daily bars snapshot for娴佸姩鎬т笌鎵撳垎
    codes = codes or []
    if max_codes is not None:
        codes = codes[:max_codes]
    for ts_code in codes:
        try:
            df = prov.get_daily_bar(ts_code, start, end, cfg.bars.daily_adj)
            save_parquet(df, daily_bar_path(cfg.paths.data_root, ts_code))
        except Exception as e:
            logger.warning("daily_bar failed for {}: {}", ts_code, e)
    logger.info("Saved daily bars for {} codes", len(codes))

    if no_minutes:
        logger.info("Skip minute bars by --no-minutes")
        return

    # Minute bars per date partition锛堜弗鏍兼ā寮忥細澶辫触鍗虫姤閿欙紝鍙厤缃噸璇曟鏁帮級
    cal = load_parquet(raw_path(cfg.paths.data_root, 'trade_cal.parquet'))
    if cal.empty:
        # derive trade dates from daily bars when calendar is missing
        import pandas as pd
        dd: set[str] = set()
        for ts_code in codes:
            p = daily_bar_path(cfg.paths.data_root, ts_code)
            df = load_parquet(p)
            if df.empty:
                continue
            dd.update(df[(df['trade_date'] >= start) & (df['trade_date'] <= end)]['trade_date'].astype(str).tolist())
        trade_dates = sorted(dd)
    else:
        trade_dates = cal[(cal['trade_date'] >= start) & (cal['trade_date'] <= end)]['trade_date'].astype(str).tolist()
    if max_days is not None:
        trade_dates = trade_dates[:max_days]

    # choose provider for minutes (override by --min-provider)
    min_prov = get_provider(min_provider) if min_provider else prov
    logs_path = cfg.paths.data_root / 'logs'
    logs_path.mkdir(parents=True, exist_ok=True)
    failures_csv = logs_path / 'fetch_failures.csv'
    if not failures_csv.exists():
        failures_csv.write_text('stage,provider,ts_code,date,reason\n', encoding='utf-8')

    for ts_code in codes:
        for d in trade_dates:
            start_dt = f"{d[:4]}-{d[4:6]}-{d[6:]} 09:30:00"
            end_dt = f"{d[:4]}-{d[4:6]}-{d[6:]} 15:00:00"
            attempt = 0
            last_exc = None
            while True:
                try:
                    df = min_prov.get_min_bar(ts_code, start_dt, end_dt, freq=cfg.bars.min_freq)
                    if df is None or df.empty:
                        raise RuntimeError(f"鍒嗛挓绾夸负绌? {ts_code} {d}")
                    save_parquet(df, min5_bar_path(cfg.paths.data_root, ts_code, d))
                    break
                except Exception as e:
                    last_exc = e
                    if attempt >= retries:
                        with open(failures_csv, 'a', encoding='utf-8') as f:
                            f.write(f"min5,{min_provider or cfg.provider},{ts_code},{d},\"{str(e).replace(',', ';')}\"\n")
                        # 涓嶄腑鏂棩绾挎垚鏋滐紝璁板綍澶辫触缁х画鍏朵粬鏍囩殑/鏃ユ湡
                        break
                    attempt += 1
                    logger.warning("min_bar閲嶈瘯 {}/{} {} {}: {}", attempt, retries, ts_code, d, e)
    logger.info("Saved minute bars with failures logged to {}", failures_csv)


def cmd_build_candidates(cfg: AppConfig, date: str) -> None:
    # Load basics
    sb = load_parquet(raw_path(cfg.paths.data_root, 'stock_basic.parquet'))
    nc = load_parquet(raw_path(cfg.paths.data_root, 'namechange.parquet'))

    # Build latest daily snapshot per ts_code up to date
    latest_rows = []
    for p in (cfg.paths.data_root / 'bars' / 'daily').glob('ts_code=*.parquet'):
        ts_code = p.stem.split('=')[1]
        df = load_parquet(p)
        if df.empty:
            continue
        df = df[df['trade_date'] <= date]
        if df.empty:
            continue
        latest_rows.append(df.iloc[-1])
    daily_latest = pd.DataFrame(latest_rows)

    uni = build_universe(
        stock_basic=sb,
        namechange=nc,
        daily_latest=daily_latest,
        min_list_days=cfg.universe.min_list_days,
        exclude_st=cfg.universe.exclude_st,
        min_amount=cfg.universe.min_amount,
        min_vol=cfg.universe.min_vol,
    )

    # Prepare daily bars mapping for scoring (lightweight)
    daily_bars: Dict[str, pd.DataFrame] = {}
    for p in (cfg.paths.data_root / 'bars' / 'daily').glob('ts_code=*.parquet'):
        ts_code = p.stem.split('=')[1]
        df = load_parquet(p)
        df = df[df['trade_date'] <= date]
        daily_bars[ts_code] = df

    cands = select_top_k(
        universe_df=uni,
        daily_bars=daily_bars,
        weekly_bars=None,
        monthly_bars=None,
        top_k=cfg.experiment.candidate_size,
    )

    out_path = cfg.paths.universe_root / f"candidate_pool_{date}.csv"
    dfout = pd.DataFrame([{
        'trade_date': date,
        'rank': c.rank,
        'ts_code': c.ts_code,
        'name': c.name,
        'score': c.score,
        'tags': c.tags or ''
    } for c in cands])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dfout.to_csv(out_path, index=False, encoding='utf-8')
    logger.success("Candidate pool saved: {} ({} rows)", out_path, len(dfout))
    # Sidecar metadata: as-of timestamp and generation hints to prevent lookahead
    try:
        cal = load_parquet(raw_path(cfg.paths.data_root, 'trade_cal.parquet'))
        prev_days = cal[cal['trade_date'] < int(date)]['trade_date'].astype(str).tolist()
        asof_day = prev_days[-1] if prev_days else date
    except Exception:
        asof_day = date
    meta = {
        'asof_timestamp': f"{asof_day[:4]}-{asof_day[4:6]}-{asof_day[6:]} 15:00:00",
        'used_features_window': 'lookback=20d, exclude current day',
        'generation_method': 'select_top_k(score_simple, daily<=asof_day)'
    }
    meta_path = out_path.with_suffix('.meta.json')
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')


def _load_strategy(name: str):
    name = name.lower()
    if name == 'baseline':
        from .strategy.baseline import BaselineStrategy, BaselineParams
        import yaml
        yml = Path('configs/strategies/baseline.yaml')
        params = BaselineParams()
        if yml.exists():
            cfg = yaml.safe_load(yml.read_text(encoding='utf-8')) or {}
            p = (cfg.get('params') or {})
            params = BaselineParams(
                buy_time=p.get('buy_time', params.buy_time),
                sell_time=p.get('sell_time', params.sell_time),
                buy_top_k=p.get('buy_top_k', params.buy_top_k),
                per_stock_cash=p.get('per_stock_cash', params.per_stock_cash),
            )
        return BaselineStrategy(params)
    if name == 'baseline_daily':
        from .strategy.baseline_daily import BaselineDaily, BaselineDailyParams
        import yaml
        yml = Path('configs/strategies/baseline_daily.yaml')
        params = BaselineDailyParams()
        if yml.exists():
            cfg = yaml.safe_load(yml.read_text(encoding='utf-8')) or {}
            p = (cfg.get('params') or {})
            params = BaselineDailyParams(
                buy_top_k=p.get('buy_top_k', params.buy_top_k),
                per_stock_cash=p.get('per_stock_cash', params.per_stock_cash),
            )
        return BaselineDaily(params)
    if name == 'time_entry_min5':
        from .strategy.time_entry_min5 import TimeEntryMin5, TimeEntryParams
        import yaml
        yml = Path('configs/strategies/time_entry_min5.yaml')
        params = TimeEntryParams()
        if yml.exists():
            cfg = yaml.safe_load(yml.read_text(encoding='utf-8')) or {}
            p = (cfg.get('params') or {})
            params = TimeEntryParams(
                entry_time=p.get('entry_time', params.entry_time),
                exit_time=p.get('exit_time', params.exit_time),
                pick_rank=p.get('pick_rank', params.pick_rank),
                top_k=p.get('top_k', params.top_k),
                max_positions=p.get('max_positions', params.max_positions),
                stop_loss_pct=p.get('stop_loss_pct', params.stop_loss_pct),
                take_profit_pct=p.get('take_profit_pct', params.take_profit_pct),
                per_stock_cash=p.get('per_stock_cash', params.per_stock_cash),
            )
        return TimeEntryMin5(params)
    if name == 'open_range_breakout':
        from .strategy.open_range_breakout import OpenRangeBreakout, ORBParams
        import yaml
        yml = Path('configs/strategies/open_range_breakout.yaml')
        params = ORBParams()
        if yml.exists():
            cfg = yaml.safe_load(yml.read_text(encoding='utf-8')) or {}
            p = (cfg.get('params') or {})
            params = ORBParams(
                range_end_time=p.get('range_end_time', params.range_end_time),
                breakout_bps=p.get('breakout_bps', params.breakout_bps),
                vol_mult=p.get('vol_mult', params.vol_mult),
                exit_time=p.get('exit_time', params.exit_time),
                pick_rank=p.get('pick_rank', params.pick_rank),
                top_k=p.get('top_k', params.top_k),
                max_positions=p.get('max_positions', params.max_positions),
                stop_loss_pct=p.get('stop_loss_pct', params.stop_loss_pct),
                per_stock_cash=p.get('per_stock_cash', params.per_stock_cash),
            )
        return OpenRangeBreakout(params)
    if name == 'vwap_reclaim_pullback':
        from .strategy.vwap_reclaim_pullback import VWAPReclaimPullback, VWAPParams
        import yaml
        yml = Path('configs/strategies/vwap_reclaim_pullback.yaml')
        params = VWAPParams()
        if yml.exists():
            cfg = yaml.safe_load(yml.read_text(encoding='utf-8')) or {}
            p = (cfg.get('params') or {})
            params = VWAPParams(
                start_time=p.get('start_time', params.start_time),
                dip_bps=p.get('dip_bps', params.dip_bps),
                exit_time=p.get('exit_time', params.exit_time),
                pick_rank=p.get('pick_rank', params.pick_rank),
                top_k=p.get('top_k', params.top_k),
                max_positions=p.get('max_positions', params.max_positions),
                stop_loss_pct=p.get('stop_loss_pct', params.stop_loss_pct),
                per_stock_cash=p.get('per_stock_cash', params.per_stock_cash),
            )
        return VWAPReclaimPullback(params)
    raise ValueError(f"Unknown strategy: {name}")


def cmd_backtest(cfg: AppConfig, start: str, end: str, strategy_names: list[str], require_trades: bool = False) -> None:
    engine = BacktestEngine(cfg)
    strategies: Dict[str, object] = {}
    expanded: list[str] = []
    for n in strategy_names:
        expanded.extend([x.strip() for x in n.split(',') if x.strip()])
    for n in expanded:
        strategies[n] = _load_strategy(n)
    res_dir = engine.run_weekly(start, end, strategies=strategies)  # type: ignore
    logger.success("Backtest finished. Results at {}", res_dir)
    if require_trades:
        import pandas as pd
        cmp = pd.read_csv(res_dir / 'compare_strategies.csv') if (res_dir / 'compare_strategies.csv').exists() else None
        if cmp is None or cmp.empty:
            raise RuntimeError('compare_strategies.csv missing; cannot validate trades')
        zero = cmp[cmp['n_trades'] == 0]
        if not zero.empty:
            names = ','.join(zero['strategy'].astype(str).tolist())
            raise RuntimeError(f"No trades for: {names}; --require-trades enforced")


def main() -> None:
    parser = argparse.ArgumentParser(description='A鑲′富鏉跨煭绾垮洖娴嬬郴缁?CLI')
    parser.add_argument('--config', default='configs/config.yaml', help='閰嶇疆鏂囦欢璺緞')

    sub = parser.add_subparsers(dest='cmd', required=True)

    p_init = sub.add_parser('init', help='鍒濆鍖栫洰褰曠粨鏋?)

    p_fetch = sub.add_parser('fetch', help='鎶撳彇鍩虹鏁版嵁銆佹棩绾夸笌鍒嗛挓绾匡紙鍒嗛挓绾垮彲鍗曠嫭鎸囧畾provider锛?)
    p_fetch.add_argument('--start', required=True, help='YYYYMMDD')
    p_fetch.add_argument('--end', required=True, help='YYYYMMDD')
    p_fetch.add_argument('--max-codes', type=int, default=None, help='闄愬埗鎶撳彇鐨勮偂绁ㄦ暟閲忥紙浠庡ご閮ㄦ埅鍙栵級')
    p_fetch.add_argument('--no-minutes', action='store_true', help='浠呮姄鍙栧熀纭€涓庢棩绾匡紝璺宠繃鍒嗛挓绾?)
    p_fetch.add_argument('--max-days', type=int, default=None, help='闄愬埗鍒嗛挓绾挎姄鍙栫殑浜ゆ槗鏃ユ暟閲忥紙浠庡尯闂磋捣濮嬫埅鍙栵級')
    p_fetch.add_argument('--retries', type=int, default=0, help='鍒嗛挓绾挎姄鍙栧け璐ラ噸璇曟鏁帮紝榛樿0锛堜弗鏍硷級')
    p_fetch.add_argument('--min-provider', choices=['eastmoney_curl','akshare','tushare','local_files'], default=None, help='浠呬緵鎶撳垎閽熺嚎鐨刾rovider瑕嗙洊')
    p_fetch.add_argument('--codes', type=str, default=None, help='閫楀彿鍒嗛殧鐨則s_code鍒楄〃锛堝湪provider鏃犳硶鎻愪緵stock_basic鏃朵娇鐢級')

    p_cand = sub.add_parser('build-candidates', help='鏋勫缓鎸囧畾浜ゆ槗鏃ョ殑鍊欓€夋睜Top20')
    p_cand.add_argument('--date', required=True, help='YYYYMMDD')

    p_cand_r = sub.add_parser('build-candidates-range', help='鎸夊尯闂存壒閲忕敓鎴愬€欓€夋睜')
    p_cand_r.add_argument('--start', required=True, help='YYYYMMDD')
    p_cand_r.add_argument('--end', required=True, help='YYYYMMDD')

    p_minp = sub.add_parser('fetch-min5-for-pool', help='浠呬负鎸囧畾浜ゆ槗鏃ョ殑鍊欓€夋睜20鏀姄鍙?鍒嗛挓绾?)
    p_minp.add_argument('--date', required=True, help='YYYYMMDD')
    p_minp.add_argument('--retries', type=int, default=1)
    p_minp.add_argument('--min-provider', choices=['eastmoney_curl','akshare','tushare','local_files'], default='eastmoney_curl')

    p_bt = sub.add_parser('backtest', help='鎸夊懆婊氬姩鍥炴祴')
    p_bt.add_argument('--start', required=True, help='YYYYMMDD')
    p_bt.add_argument('--end', required=True, help='YYYYMMDD')
    p_bt.add_argument('--strategies', nargs='+', default=['baseline'])
    p_bt.add_argument('--require-trades', action='store_true', help='鑻ョ瓥鐣ユ棤浜ゆ槗鍒欐姤閿欓€€鍑猴紙soft-fail->hard-fail锛?)

    p_doc = sub.add_parser('doctor', help='鏁版嵁涓庨厤缃瘖鏂?)
    p_doc.add_argument('--start', required=True, help='YYYYMMDD')
    p_doc.add_argument('--end', required=True, help='YYYYMMDD')

    p_llm = sub.add_parser('llm-rank', help='鐩樺墠 LLM 鑽愯偂鎺掑簭锛堜弗鏍糐SON锛屾棤fallback锛?)
    p_llm.add_argument('--date', required=True, help='YYYYMMDD')
    p_llm.add_argument('--template', required=True, help='妯℃澘ID锛屽 momentum_v1')
    p_llm.add_argument('--force', action='store_true', help='寮哄埗閲嶈窇骞惰鐩栫紦瀛?)

    p_tune = sub.add_parser('tune', help='鍥炴函閫夋嫨鏈€浼樼粍鍚堢瓥鐣ュ苟钀界洏 current_policy')
    p_tune.add_argument('--end', required=True, help='YYYYMMDD')
    p_tune.add_argument('--lookback-weeks', type=int, default=12)
    p_tune.add_argument('--eval-weeks', type=int, default=4)
    p_tune.add_argument('--templates', type=str, required=True, help='閫楀彿鍒嗛殧妯℃澘ID鍒楄〃')
    p_tune.add_argument('--entries', type=str, default='baseline', help='閫楀彿鍒嗛殧entry绛栫暐ID鍒楄〃锛岄鏈熷彲鐢?baseline')
    p_tune.add_argument('--exits', type=str, default='next_day_time_exit', help='閫楀彿鍒嗛殧exit妯℃澘ID鍒楄〃锛岄鏈熶娇鐢ㄥ浐瀹氭椂闂村崠鍑?)
    p_tune.add_argument('--min-trades', type=int, default=10)
    p_tune.add_argument('--topk', type=int, default=3)
    p_tune.add_argument('--wf-train-weeks', type=int, default=0, help='Walk-forward 训练周数（0则关闭WF评估）')
    p_tune.add_argument('--wf-test-weeks', type=int, default=0, help='Walk-forward 测试周数')
    p_tune.add_argument('--wf-steps', type=int, default=0, help='Walk-forward 步数')

    p_llmrun = sub.add_parser('llm-run', help='鎸?current_policy 鐩樺墠LLM鑽愯偂骞舵墽琛?)
    p_llmrun.add_argument('--start', required=True)
    p_llmrun.add_argument('--end', required=True)
    p_llmrun.add_argument('--run-id', required=True)

    p_minr = sub.add_parser('fetch-min5-range', help='鎸夊尯闂翠负姣忓ぉ鍊欓€夋睜20鏀姄鍙?鍒嗛挓绾?)
    p_minr.add_argument('--start', required=True)
    p_minr.add_argument('--end', required=True)
    p_minr.add_argument('--min-provider', choices=['eastmoney_curl','akshare','tushare','local_files'], default='eastmoney_curl')
    p_minr.add_argument('--retries', type=int, default=2)

    args = parser.parse_args()
    cfg = AppConfig.load(args.config)

    if args.cmd == 'init':
        cmd_init(cfg)
    elif args.cmd == 'fetch':
        codes = args.codes.split(',') if getattr(args, 'codes', None) else None
        cmd_fetch(cfg, args.start, args.end, max_codes=args.max_codes, no_minutes=args.no_minutes, max_days=args.max_days, retries=args.retries, min_provider=args.min_provider, codes=codes)
    elif args.cmd == 'build-candidates':
        cmd_build_candidates(cfg, args.date)
    elif args.cmd == 'build-candidates-range':
        cal = load_parquet(raw_path(cfg.paths.data_root, 'trade_cal.parquet'))
        if cal.empty:
            raise RuntimeError('缂哄皯浜ゆ槗鏃ュ巻 trade_cal.parquet锛屾棤娉曠敓鎴愬€欓€夋睜')
        days = cal[(cal['trade_date'] >= args.start) & (cal['trade_date'] <= args.end)]['trade_date'].astype(str).tolist()
        for d in days:
            cmd_build_candidates(cfg, d)
    elif args.cmd == 'doctor':
        run_doctor(cfg, args.start, args.end)
    elif args.cmd == 'llm-rank':
        llm_rank(cfg, args.date, args.template, force=args.force)
    elif args.cmd == 'tune':
        templates = [t.strip() for t in args.templates.split(',') if t.strip()]
        entries = [t.strip() for t in args.entries.split(',') if t.strip()]
        exits = [t.strip() for t in args.exits.split(',') if t.strip()]
        # Optional walk-forward arguments if present
        wf_train = getattr(args, 'wf_train_weeks', 0)
        wf_test = getattr(args, 'wf_test_weeks', 0)
        wf_steps = getattr(args, 'wf_steps', 0)
        tune_policy(cfg, args.end, args.lookback_weeks, args.eval_weeks, templates, entries, exits, min_trades=args.min_trades, topk=args.topk, wf_train_weeks=wf_train, wf_test_weeks=wf_test, wf_steps=wf_steps)
    elif args.cmd == 'llm-run':
        store = PolicyStore(cfg)
        pol = store.load_current()
        start, end = args.start, args.end
        days = load_parquet(raw_path(cfg.paths.data_root, 'trade_cal.parquet'))
        days = days[(days['trade_date'] >= start) & (days['trade_date'] <= end)]['trade_date'].astype(str).tolist()
        ranked_map = {}
        for d in days:
            df = llm_rank(cfg, d, pol['ranker_template_id'], force=False, topk=int(pol.get('topk', 3)))
            ranked_map[d] = df['ts_code'].astype(str).tolist()
        # Map policy to strategy
        from .cli import _load_strategy as load_strat  # self-import safe
        strat_name = 'time_entry_min5'  # 棣栨湡鐢ㄥ浐瀹氭椂闂村叆鍦?        strat = load_strat(strat_name)
        if hasattr(strat, 'params') and hasattr(strat.params, 'exit_time'):
            strat.params.exit_time = '10:00:00'
        if hasattr(strat, 'params') and hasattr(strat.params, 'top_k'):
            strat.params.top_k = int(pol.get('topk', 3))
        # Run
        engine = BacktestEngine(cfg)
        prev_run_id = cfg.experiment.run_id
        cfg.experiment.run_id = args.run_id
        res = engine.run_weekly(start, end, strategies={strat_name: strat}, ranked_map=ranked_map)  # type: ignore
        cfg.experiment.run_id = prev_run_id
        # Save used policy
        (res / 'policy_used.json').write_text(json.dumps(pol, ensure_ascii=False, indent=2), encoding='utf-8')
        # Save llm outputs index
        (res / 'llm_used').mkdir(parents=True, exist_ok=True)
        (res / 'llm_used' / 'dates.txt').write_text('\n'.join(days), encoding='utf-8')
    elif args.cmd == 'fetch-min5-range':
        # For each day in range, read candidate pool and fetch 5min for its 20 codes
        cal = load_parquet(raw_path(cfg.paths.data_root, 'trade_cal.parquet'))
        if cal.empty:
            raise RuntimeError('缂哄皯浜ゆ槗鏃ュ巻 trade_cal.parquet')
        days = cal[(cal['trade_date'] >= args.start) & (cal['trade_date'] <= args.end)]['trade_date'].astype(str).tolist()
        for d in days:
            f = cfg.paths.universe_root / f"candidate_pool_{d}.csv"
            if not f.exists():
                raise RuntimeError(f'缂哄皯鍊欓€夋睜 {f}')
            import pandas as pd
            codes = pd.read_csv(f)['ts_code'].astype(str).tolist()
            # strict: any failure raises
            cmd_fetch(cfg, d, d, max_codes=len(codes), no_minutes=False, max_days=1, retries=args.retries, min_provider=args.min_provider, codes=codes)
    elif args.cmd == 'fetch-min5-for-pool':
        import pandas as pd
        d = args.date
        f = cfg.paths.universe_root / f"candidate_pool_{d}.csv"
        if not f.exists():
            raise RuntimeError(f"缂哄皯鍊欓€夋睜: {f}")
        cands = pd.read_csv(f)['ts_code'].astype(str).tolist()
        # call cmd_fetch minute stage only for these codes
        cmd_fetch(cfg, d, d, max_codes=len(cands), no_minutes=False, max_days=1, retries=args.retries, min_provider=args.min_provider, codes=cands)
    elif args.cmd == 'backtest':
        req = getattr(args, 'require_trades', False)
        cmd_backtest(cfg, args.start, args.end, args.strategies, require_trades=req)


if __name__ == '__main__':
    main()
