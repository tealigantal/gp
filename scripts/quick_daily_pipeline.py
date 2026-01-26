import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from gpbt.config import AppConfig
from gpbt.providers.eastmoney_curl_provider import EastMoneyCurlProvider
from gpbt.storage import save_parquet, daily_bar_path
from gpbt.universe import build_universe, select_top_k
from gpbt.engine.backtest import BacktestEngine
from gpbt.strategy.baseline_daily import BaselineDaily, BaselineDailyParams


def daterange(start: str, end: str):
    import datetime as dt
    d0 = dt.datetime.strptime(start, '%Y%m%d').date()
    d1 = dt.datetime.strptime(end, '%Y%m%d').date()
    d = d0
    while d <= d1:
        yield d.strftime('%Y%m%d')
        d = d + dt.timedelta(days=1)


def main():
    if len(sys.argv) < 4:
        print('Usage: python scripts/quick_daily_pipeline.py YYYYMMDD YYYYMMDD CODE1,CODE2,... (e.g., 20230103 20230110 600000.SH,000001.SZ)')
        sys.exit(1)
    start, end, codes_str = sys.argv[1], sys.argv[2], sys.argv[3]
    codes = [c.strip() for c in codes_str.split(',') if c.strip()]

    cfg = AppConfig.load('configs/config.yaml')
    cfg.ensure_dirs()

    prov = EastMoneyCurlProvider()
    # Fetch and save daily bars
    for ts in codes:
        df = prov.get_daily_bar(ts, start, end, adj='qfq')
        save_parquet(df, daily_bar_path(cfg.paths.data_root, ts))

    # Build candidate pools for each calendar day (only if we have any bar that day)
    for d in daterange(start, end):
        latest_rows = []
        daily_bars = {}
        for ts in codes:
            p = daily_bar_path(cfg.paths.data_root, ts)
            df = pd.read_parquet(p) if p.exists() else pd.DataFrame()
            df = df[df['trade_date'] <= d]
            if df.empty:
                continue
            latest_rows.append(df.iloc[-1])
            daily_bars[ts] = df
        if not latest_rows:
            continue
        daily_latest = pd.DataFrame(latest_rows)
        sb = pd.DataFrame({'ts_code': list(daily_bars.keys())})
        nc = pd.DataFrame()
        uni = build_universe(
            stock_basic=sb,
            namechange=nc,
            daily_latest=daily_latest,
            min_list_days=0,
            exclude_st=False,
            min_amount=0,
            min_vol=0,
        )
        cands = select_top_k(uni, daily_bars, None, None, top_k=min(len(uni), cfg.experiment.candidate_size))
        out_path = cfg.paths.universe_root / f"candidate_pool_{d}.csv"
        pd.DataFrame([
            {'trade_date': d, 'rank': c.rank, 'ts_code': c.ts_code, 'name': c.name, 'score': c.score, 'tags': c.tags or ''}
            for c in cands
        ]).to_csv(out_path, index=False, encoding='utf-8')

    # Run backtest daily strategy
    engine = BacktestEngine(cfg)
    strat = BaselineDaily(BaselineDailyParams())
    res_dir = engine.run_weekly(start, end, strategies={'baseline_daily': strat})
    print('Results at:', res_dir)


if __name__ == '__main__':
    main()

