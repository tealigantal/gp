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
        sb = pd.DataFrame({'ts_code': codes, 'symbol': [c.split('.')[0] for c in codes], 'name': ['']*len(codes), 'exchange': ['']*len(codes), 'market': ['主板']*len(codes), 'list_date': ['']*len(codes), 'delist_date': ['']*len(codes)})
        save_parquet(sb, raw_path(cfg.paths.data_root, 'stock_basic.parquet'))

    # Name change
    nc = prov.get_namechange(None)
    save_parquet(nc, raw_path(cfg.paths.data_root, 'namechange.parquet'))
    logger.info("Saved namechange: {} rows", len(nc))

    # Trade calendar
    cal = prov.get_trade_calendar(start, end)
    save_parquet(cal, raw_path(cfg.paths.data_root, 'trade_cal.parquet'))
    logger.info("Saved trade_cal: {} rows", len(cal))

    # Daily bars snapshot for流动性与打分
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

    # Minute bars per date partition（严格模式：失败即报错，可配置重试次数）
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
                        raise RuntimeError(f"分钟线为空: {ts_code} {d}")
                    save_parquet(df, min5_bar_path(cfg.paths.data_root, ts_code, d))
                    break
                except Exception as e:
                    last_exc = e
                    if attempt >= retries:
                        with open(failures_csv, 'a', encoding='utf-8') as f:
                            f.write(f"min5,{min_provider or cfg.provider},{ts_code},{d},\"{str(e).replace(',', ';')}\"\n")
                        # 不中断日线成果，记录失败继续其他标的/日期
                        break
                    attempt += 1
                    logger.warning("min_bar重试 {}/{} {} {}: {}", attempt, retries, ts_code, d, e)
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


def cmd_backtest(cfg: AppConfig, start: str, end: str, strategy_names: list[str]) -> None:
    engine = BacktestEngine(cfg)
    strategies: Dict[str, object] = {}
    expanded: list[str] = []
    for n in strategy_names:
        expanded.extend([x.strip() for x in n.split(',') if x.strip()])
    for n in expanded:
        strategies[n] = _load_strategy(n)
    res_dir = engine.run_weekly(start, end, strategies=strategies)  # type: ignore
    logger.success("Backtest finished. Results at {}", res_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description='A股主板短线回测系统 CLI')
    parser.add_argument('--config', default='configs/config.yaml', help='配置文件路径')

    sub = parser.add_subparsers(dest='cmd', required=True)

    p_init = sub.add_parser('init', help='初始化目录结构')

    p_fetch = sub.add_parser('fetch', help='抓取基础数据、日线与分钟线（分钟线可单独指定provider）')
    p_fetch.add_argument('--start', required=True, help='YYYYMMDD')
    p_fetch.add_argument('--end', required=True, help='YYYYMMDD')
    p_fetch.add_argument('--max-codes', type=int, default=None, help='限制抓取的股票数量（从头部截取）')
    p_fetch.add_argument('--no-minutes', action='store_true', help='仅抓取基础与日线，跳过分钟线')
    p_fetch.add_argument('--max-days', type=int, default=None, help='限制分钟线抓取的交易日数量（从区间起始截取）')
    p_fetch.add_argument('--retries', type=int, default=0, help='分钟线抓取失败重试次数，默认0（严格）')
    p_fetch.add_argument('--min-provider', choices=['eastmoney_curl','akshare','tushare','local_files'], default=None, help='仅供抓分钟线的provider覆盖')
    p_fetch.add_argument('--codes', type=str, default=None, help='逗号分隔的ts_code列表（在provider无法提供stock_basic时使用）')

    p_cand = sub.add_parser('build-candidates', help='构建指定交易日的候选池Top20')
    p_cand.add_argument('--date', required=True, help='YYYYMMDD')

    p_cand_r = sub.add_parser('build-candidates-range', help='按区间批量生成候选池')
    p_cand_r.add_argument('--start', required=True, help='YYYYMMDD')
    p_cand_r.add_argument('--end', required=True, help='YYYYMMDD')

    p_minp = sub.add_parser('fetch-min5-for-pool', help='仅为指定交易日的候选池20支抓取5分钟线')
    p_minp.add_argument('--date', required=True, help='YYYYMMDD')
    p_minp.add_argument('--retries', type=int, default=1)
    p_minp.add_argument('--min-provider', choices=['eastmoney_curl','akshare','tushare','local_files'], default='eastmoney_curl')

    p_bt = sub.add_parser('backtest', help='按周滚动回测')
    p_bt.add_argument('--start', required=True, help='YYYYMMDD')
    p_bt.add_argument('--end', required=True, help='YYYYMMDD')
    p_bt.add_argument('--strategies', nargs='+', default=['baseline'])

    p_doc = sub.add_parser('doctor', help='数据与配置诊断')
    p_doc.add_argument('--start', required=True, help='YYYYMMDD')
    p_doc.add_argument('--end', required=True, help='YYYYMMDD')

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
            raise RuntimeError('缺少交易日历 trade_cal.parquet，无法生成候选池')
        days = cal[(cal['trade_date'] >= args.start) & (cal['trade_date'] <= args.end)]['trade_date'].astype(str).tolist()
        for d in days:
            cmd_build_candidates(cfg, d)
    elif args.cmd == 'doctor':
        run_doctor(cfg, args.start, args.end)
    elif args.cmd == 'fetch-min5-for-pool':
        import pandas as pd
        d = args.date
        f = cfg.paths.universe_root / f"candidate_pool_{d}.csv"
        if not f.exists():
            raise RuntimeError(f"缺少候选池: {f}")
        cands = pd.read_csv(f)['ts_code'].astype(str).tolist()
        # call cmd_fetch minute stage only for these codes
        cmd_fetch(cfg, d, d, max_codes=len(cands), no_minutes=False, max_days=1, retries=args.retries, min_provider=args.min_provider, codes=cands)
    elif args.cmd == 'backtest':
        cmd_backtest(cfg, args.start, args.end, args.strategies)


if __name__ == '__main__':
    main()
