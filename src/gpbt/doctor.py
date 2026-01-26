from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pandas as pd
from loguru import logger

from .config import AppConfig
from .storage import load_parquet, daily_bar_path, min5_bar_path


def _read_trade_calendar(cfg: AppConfig, start: str, end: str) -> List[str]:
    cal = load_parquet(cfg.paths.data_root / 'raw' / 'trade_cal.parquet')
    if cal.empty:
        return []
    days = cal[(cal['trade_date'] >= start) & (cal['trade_date'] <= end)]['trade_date'].astype(str).tolist()
    return days


def run_doctor(cfg: AppConfig, start: str, end: str) -> Path:
    report: Dict = {
        'config': {
            'provider': cfg.provider,
            'data_root': str(cfg.paths.data_root),
            'code_format': 'ts_code',
        },
        'checks': {}
    }

    results_dir = cfg.paths.results_root / f"run_{cfg.experiment.run_id}"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / 'doctor_report.json'

    # 交易日历
    days = _read_trade_calendar(cfg, start, end)
    if not days:
        logger.error("缺少交易日历 data/raw/trade_cal.parquet。请先运行: python gpbt.py fetch --start {} --end {} --no-minutes", start, end)
        report['checks']['trade_calendar'] = {'ok': False, 'message': 'missing trade_cal.parquet'}
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info("报告已写入 {}", out_path)
        return out_path

    # 日线覆盖率
    # 统计：每天有日线数据的代码数量
    daily_dir = cfg.paths.data_root / 'bars' / 'daily'
    codes = [p.stem.split('=')[1] for p in daily_dir.glob('ts_code=*.parquet')]
    missing_daily: Dict[str, List[str]] = {d: [] for d in days}
    daily_counts: Dict[str, int] = {d: 0 for d in days}
    for c in codes:
        df = load_parquet(daily_bar_path(cfg.paths.data_root, c))
        for d in days:
            if not df.empty and (df['trade_date'] == d).any():
                daily_counts[d] += 1
            else:
                missing_daily[d].append(c)
    report['checks']['daily_coverage'] = {
        'total_days': len(days),
        'codes': len(codes),
        'per_day_counts': daily_counts,
    }

    # 候选池存在性与行数
    need_rows = cfg.experiment.candidate_size
    missing_candidates: List[str] = []
    wrong_rows: Dict[str, int] = {}
    for d in days:
        f = cfg.paths.universe_root / f"candidate_pool_{d}.csv"
        if not f.exists():
            missing_candidates.append(d)
        else:
            df = pd.read_csv(f)
            if len(df) != need_rows:
                wrong_rows[d] = len(df)
    report['checks']['candidates'] = {
        'missing_days': missing_candidates,
        'wrong_rows': wrong_rows,
        'expected_rows': need_rows,
    }

    # 5min 覆盖率（候选池×交易日）
    missing_min5: Dict[str, List[str]] = {}
    covered = 0
    total = 0
    for d in days:
        cand_path = cfg.paths.universe_root / f"candidate_pool_{d}.csv"
        if not cand_path.exists():
            continue
        ts_list = pd.read_csv(cand_path)['ts_code'].astype(str).tolist()
        for ts in ts_list:
            total += 1
            p = min5_bar_path(cfg.paths.data_root, ts, d)
            if p.exists():
                covered += 1
            else:
                missing_min5.setdefault(d, []).append(ts)
    report['checks']['min5_coverage'] = {
        'pairs_total': total,
        'pairs_covered': covered,
        'missing_pairs': missing_min5,
    }

    # fetch失败清单
    failures = cfg.paths.data_root / 'logs' / 'fetch_failures.csv'
    if failures.exists():
        report['checks']['fetch_failures_csv'] = str(failures)

    # 建议下一步
    remedies: List[str] = []
    if missing_candidates:
        remedies.append(f"缺少候选池: {len(missing_candidates)} 天。运行: python gpbt.py build-candidates-range --start {start} --end {end}")
    if any(v for v in missing_min5.values()):
        remedies.append("分钟线不全：建议使用 --min-provider eastmoney_curl 并重试，例如: "
                        f"python gpbt.py fetch --start {start} --end {end} --min-provider eastmoney_curl --retries 2 --max-codes 30 --max-days 4")
    if not codes:
        remedies.append(f"日线为空：先确保 provider 可用，然后运行: python gpbt.py fetch --start {start} --end {end} --no-minutes")
    report['next_steps'] = remedies

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    # 控制台输出摘要
    logger.info("Doctor 报告:")
    logger.info(json.dumps(report, ensure_ascii=False, indent=2))
    return out_path

