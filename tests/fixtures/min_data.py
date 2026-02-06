from __future__ import annotations

from pathlib import Path
import pandas as pd


def seed_min_dataset(root: Path) -> dict:
    """Seed a minimal offline dataset for two codes and one minute day.
    Returns useful paths dict.
    """
    data = root / 'data'
    uni = root / 'universe'
    res = root / 'results'
    for p in [data / 'raw', data / 'bars' / 'daily', data / 'bars' / 'min5', uni, res]:
        p.mkdir(parents=True, exist_ok=True)

    # Trade calendar: three days to allow T+1 exits
    cal = pd.DataFrame({'trade_date': ['20260105','20260106','20260107']})
    cal.to_parquet(data / 'raw' / 'trade_cal.parquet', index=False)

    # Daily bars for three codes (third for LLM ranking top3)
    d1 = pd.DataFrame({
        'trade_date': ['20260105','20260106','20260107'],
        'open': [10.0, 10.5],
        'high': [10.2, 10.8, 10.9],
        'low': [9.8, 10.4, 10.6],
        'close': [10.1, 10.7, 10.65],
        'vol': [100000, 120000, 110000],
        'amount': [1.2e7, 1.5e7, 1.4e7],
        'ts_code': ['000001.SZ','000001.SZ','000001.SZ'],
    })
    d1.to_parquet(data / 'bars' / 'daily' / 'ts_code=000001.SZ.parquet', index=False)
    d2 = pd.DataFrame({
        'trade_date': ['20260105','20260106','20260107'],
        'open': [20.0, 20.2],
        'high': [20.5, 20.8, 20.9],
        'low': [19.8, 20.1, 20.0],
        'close': [20.1, 20.7, 20.4],
        'vol': [150000, 160000, 140000],
        'amount': [1.8e7, 2.0e7, 1.7e7],
        'ts_code': ['000002.SZ','000002.SZ','000002.SZ'],
    })
    d2.to_parquet(data / 'bars' / 'daily' / 'ts_code=000002.SZ.parquet', index=False)
    d3 = pd.DataFrame({
        'trade_date': ['20260105','20260106'],
        'open': [30.0, 30.2],
        'high': [30.5, 30.8],
        'low': [29.8, 30.1],
        'close': [30.1, 30.3],
        'vol': [80000, 90000],
        'amount': [1.0e7, 1.1e7],
        'ts_code': ['000003.SZ','000003.SZ'],
    })
    d3.to_parquet(data / 'bars' / 'daily' / 'ts_code=000003.SZ.parquet', index=False)

    # Minute bars for 20260106 and 20260107 to trigger strategies and exits
    def mkt(ts_code: str):
        times = [
            '2026-01-06 09:30:00',
            '2026-01-06 09:35:00',
            '2026-01-06 10:00:00',
            '2026-01-06 10:05:00',
            '2026-01-06 10:10:00',
            '2026-01-07 09:30:00',
            '2026-01-07 10:00:00',
            '2026-01-07 10:05:00',
        ]
        # Craft OHLC so that at 10:00 close confirms and 10:05 breakouts
        df = pd.DataFrame({
            'trade_time': times,
            'open': [10.0, 10.1, 10.2, 10.25, 10.3, 10.4, 10.45, 10.5],
            'high': [10.1, 10.2, 10.25, 10.35, 10.4, 10.45, 10.5, 10.55],
            'low': [9.9, 10.0, 10.15, 10.2, 10.25, 10.35, 10.4, 10.45],
            'close': [10.05, 10.15, 10.22, 10.32, 10.38, 10.42, 10.48, 10.52],
            'vol': [1000, 1200, 1500, 1800, 1600, 1700, 1600, 1500],
            'amount': [1.0e6, 1.1e6, 1.2e6, 1.3e6, 1.2e6, 1.25e6, 1.2e6, 1.15e6],
            'ts_code': [ts_code]*5,
        })
        return df
    mb1 = mkt('000001.SZ')
    (data / 'bars' / 'min5' / 'ts_code=000001.SZ').mkdir(parents=True, exist_ok=True)
    mb1.to_parquet(data / 'bars' / 'min5' / 'ts_code=000001.SZ' / 'date=20260106.parquet', index=False)
    mb2 = mkt('000002.SZ')
    (data / 'bars' / 'min5' / 'ts_code=000002.SZ').mkdir(parents=True, exist_ok=True)
    mb2.to_parquet(data / 'bars' / 'min5' / 'ts_code=000002.SZ' / 'date=20260106.parquet', index=False)

    # Candidate pool for that day
    (root / 'universe').mkdir(parents=True, exist_ok=True)
    (root / 'universe' / 'candidate_pool_20260106.csv').write_text('ts_code\n000001.SZ\n000002.SZ\n000003.SZ\n' + '\n'.join(['000001.SZ']*17), encoding='utf-8')
    # Meta with as-of D-1 15:00
    meta = {
        'trade_date': '2026-01-06',
        'asof_datetime': '2026-01-05 15:00:00',
        'selector_name': 'fixture',
        'selector_params': {},
        'filters_applied': {}
    }
    import json as _json
    (root / 'universe' / 'candidate_pool_20260106.meta.json').write_text(_json.dumps(meta, ensure_ascii=False), encoding='utf-8')

    return {'data_root': data, 'universe_root': uni, 'results_root': res}
