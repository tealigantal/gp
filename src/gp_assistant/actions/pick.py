from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Local helpers to avoid import name clash with top-level gpbt.py shadowing the gpbt package.
def _load_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _raw_path(data_root: Path, name: str) -> Path:
    return data_root / 'raw' / name


def _daily_bar_path(data_root: Path, ts_code: str) -> Path:
    return data_root / 'bars' / 'daily' / f"ts_code={ts_code}.parquet"
from ..tools.gpbt_runner import run_gpbt
from ..tools.doctor_reader import read_doctor


@dataclass
class PickResult:
    date: str
    topk: int
    template: str
    mode: str
    provider: str
    ranked: List[Dict[str, Any]]
    data_status: Dict[str, Any]
    out_file: Path
    trace: List[Dict[str, Any]]


TEMPLATE_SYNONYMS = {
    '动量': 'momentum_v1',
    '回踩': 'pullback_v1',
    '防御': 'defensive_v1',
}


def parse_pick_text(text: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Parse natural text for date/topk/template.
    - Dates: YYYYMMDD | YYYY-MM-DD | YYYY/MM/DD
    - TopK: top5 | Top 5 | top 5 | 前5 | 前 5
    - Templates: 动量/回踩/防御 to mapped IDs
    Returns (date, topk, template) where values may be None if not found.
    """
    t = text.strip()
    date = None
    topk = None
    template = None
    # date variants
    m = re.search(r"(20\d{2}[-/ ]?\d{2}[-/ ]?\d{2})", t)
    if m:
        ds = re.sub(r"[-/ ]", "", m.group(1))
        if len(ds) == 8:
            date = ds
    # topk variants
    m2 = re.search(r"(?:top\s*|Top\s*|TOP\s*|前\s*)(\d+)", t)
    if m2:
        try:
            topk = int(m2.group(1))
        except Exception:
            pass
    # synonyms for template
    for zh, tid in TEMPLATE_SYNONYMS.items():
        if zh in t:
            template = tid
            break
    return date, topk, template


def _latest_pool_date(universe_root: Path) -> Optional[str]:
    pats = list(universe_root.glob('candidate_pool_*.csv'))
    if not pats:
        return None
    dates: List[str] = []
    for p in pats:
        m = re.match(r"candidate_pool_(\d{8})\.csv$", p.name)
        if m:
            dates.append(m.group(1))
    if not dates:
        return None
    return sorted(dates)[-1]


def _last_trade_date_from_calendar(data_root: Path, today: Optional[str] = None) -> Optional[str]:
    cal = _load_parquet(_raw_path(data_root, 'trade_cal.parquet'))
    if cal.empty:
        return None
    arr = cal['trade_date'].astype(str).tolist()
    if today and today.isdigit():
        arr = [d for d in arr if d <= today]
    return sorted(arr)[-1] if arr else None


def _ensure_inited(python_exe: str, repo: Path, session, trace: List[Dict[str, Any]]) -> None:
    code, out, err, dt = run_gpbt(python_exe, repo, 'init', [], allow=['init'])
    rec = {'tool': 'gpbt', 'cmd': ['init'], 'code': code, 'seconds': dt}
    try:
        if session is not None:
            session.append('tool', 'gpbt', {'cmd': ['init'], 'code': code, 'stderr': err[:2000], 'seconds': dt})
    except Exception:
        pass
    trace.append(rec)


def _ensure_candidate_pool(python_exe: str, repo: Path, session, date: str, trace: List[Dict[str, Any]]) -> None:
    f = repo / 'universe' / f'candidate_pool_{date}.csv'
    if f.exists():
        return
    code, out, err, dt = run_gpbt(python_exe, repo, 'build-candidates-range', ['--start', date, '--end', date], allow=['build-candidates-range'])
    try:
        if session is not None:
            session.append('tool', 'gpbt', {'cmd': ['build-candidates-range','--start',date,'--end',date], 'code': code, 'stderr': err[:2000], 'seconds': dt})
    except Exception:
        pass
    trace.append({'tool':'gpbt','cmd':['build-candidates-range','--start',date,'--end',date],'code':code,'seconds':dt})
    if code != 0:
        raise RuntimeError(f'Failed to build candidate pool for {date}: {err or out}')


def _doctor(repo: Path, session, start: str, end: str, trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    import json
    # Prefer reading latest doctor in results; if missing, run
    code, out, err, dt = run_gpbt(os.sys.executable, repo, 'doctor', ['--start', start, '--end', end], allow=['doctor'])
    try:
        if session is not None:
            session.append('tool', 'gpbt', {'cmd': ['doctor','--start',start,'--end',end], 'code': code, 'stderr': err[:2000], 'seconds': dt})
    except Exception:
        pass
    trace.append({'tool':'gpbt','cmd':['doctor','--start',start,'--end',end],'code':code,'seconds':dt})
    # Read latest
    rep = read_doctor(repo / 'results')
    return rep or {}


def _detect_daily_gaps(repo: Path, date: str, pool_codes: List[str]) -> List[str]:
    gaps: List[str] = []
    data_root = repo / 'data'
    for ts in pool_codes:
        df = _load_parquet(_daily_bar_path(data_root, ts))
        if df.empty or not (df['trade_date'].astype(str) == date).any():
            gaps.append(ts)
    return gaps


def _fetch_daily_for_codes(repo: Path, session, date: str, codes: List[str], trace: List[Dict[str, Any]]) -> None:
    if not codes:
        return
    args = ['--start', date, '--end', date, '--no-minutes', '--codes', ','.join(codes)]
    code, out, err, dt = run_gpbt(os.sys.executable, repo, 'fetch', args, allow=['fetch'])
    try:
        if session is not None:
            session.append('tool', 'gpbt', {'cmd': ['fetch'] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
    except Exception:
        pass
    trace.append({'tool':'gpbt','cmd':['fetch']+args,'code':code,'seconds':dt})


def _fetch_min5_for_pool(repo: Path, session, date: str, trace: List[Dict[str, Any]], min_provider: Optional[str] = None) -> None:
    args = ['--date', date]
    if min_provider:
        args += ['--min-provider', min_provider]
    # default retries 2
    args += ['--retries', '2']
    code, out, err, dt = run_gpbt(os.sys.executable, repo, 'fetch-min5-for-pool', args, allow=['fetch-min5-for-pool'])
    try:
        if session is not None:
            session.append('tool', 'gpbt', {'cmd': ['fetch-min5-for-pool'] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
    except Exception:
        pass
    trace.append({'tool':'gpbt','cmd':['fetch-min5-for-pool']+args,'code':code,'seconds':dt})


def _rank_llm(repo: Path, session, date: str, template: str, topk: int, trace: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]], str]:
    # Returns (provider, ranked_rows, raw_text)
    allow = ['llm-rank']
    args = ['--date', date, '--template', template]
    # topk is enforced inside ranker; still pass for clarity if CLI supports
    try:
        args += ['--topk', str(topk)]
    except Exception:
        pass
    code, out, err, dt = run_gpbt(os.sys.executable, repo, 'llm-rank', args, allow=allow)
    try:
        if session is not None:
            session.append('tool', 'gpbt', {'cmd': ['llm-rank'] + args, 'code': code, 'stderr': err[:2000], 'seconds': dt})
    except Exception:
        pass
    trace.append({'tool':'gpbt','cmd':['llm-rank']+args,'code':code,'seconds':dt})
    # Read ranked CSV
    ranked_csv = repo / 'universe' / f'candidate_pool_{date}_ranked_{template}.csv'
    if not ranked_csv.exists():
        raise RuntimeError('ranked CSV missing, llm-rank failed')
    rdf = pd.read_csv(ranked_csv)
    ranked = rdf.to_dict(orient='records')
    # Read raw text
    out_file = repo / 'data' / 'llm_cache' / 'outputs' / f'date={date}' / f'template={template}.json'
    raw = out_file.read_text(encoding='utf-8') if out_file.exists() else ''
    # Inspect raw for provider hint
    provider = 'llm'
    try:
        obj = json.loads(raw)
        provider = obj.get('_provider', provider)
    except Exception:
        pass
    return provider, ranked, raw


def _mark_holdings_and_exclusions(ranked: List[Dict[str, Any]], positions: Optional[Dict[str, int]], exclusions: Optional[List[str]], no_holdings: bool) -> List[Dict[str, Any]]:
    def code_match(ts: str, key: str) -> bool:
        # match on full or suffix 6-digit
        if ts == key:
            return True
        if key.isdigit() and ts.endswith(key):
            return True
        return False
    out: List[Dict[str, Any]] = []
    for r in ranked:
        ts = str(r.get('ts_code'))
        if exclusions and any(code_match(ts, ex) for ex in exclusions):
            continue
        if positions and any(code_match(ts, k) for k in positions.keys()):
            r = dict(r)
            r['holding'] = True
            if no_holdings:
                # skip holdings if filter enabled
                continue
        out.append(r)
    # re-assign rank after filtering to keep 1..N
    for i, rr in enumerate(out, start=1):
        rr['rank'] = i
    return out


def _suggest_qty(repo: Path, date: str, ranked: List[Dict[str, Any]], cash: Optional[float]) -> None:
    if not cash or cash <= 0:
        return
    prev = _last_trade_date_from_calendar(repo / 'data', date)
    n = max(1, len(ranked))
    budget_per = cash / n
    for r in ranked:
        ts = str(r.get('ts_code'))
        try:
            df = _load_parquet(_daily_bar_path(repo / 'data', ts))
            if df.empty:
                continue
            ddf = df[df['trade_date'].astype(str) <= (prev or date)].sort_values('trade_date')
            if ddf.empty:
                continue
            px = float(ddf.iloc[-1]['close'])
            qty = int((budget_per // (px * 100.0)) * 100)
            if qty > 0:
                r['suggest_qty'] = qty
        except Exception:
            continue


def pick_once(repo_root: Path, session, *, date: Optional[str], topk: int, template: str, tier: Optional[str] = None, mode: str = 'auto', positions: Optional[Dict[str,int]] = None, cash: Optional[float] = None, exclusions: Optional[List[str]] = None, no_holdings: bool = False) -> PickResult:
    repo = Path(repo_root)
    python_exe = os.sys.executable
    trace: List[Dict[str, Any]] = []
    # 1) init
    _ensure_inited(python_exe, repo, session, trace)
    # 2) decide date
    d = date
    if not d:
        d = _latest_pool_date(repo / 'universe')
    if not d:
        # Last trading day from calendar (<= today)
        today = None
        try:
            from datetime import datetime
            today = datetime.today().strftime('%Y%m%d')
        except Exception:
            pass
        d = _last_trade_date_from_calendar(repo / 'data', today)
    if not d:
        raise RuntimeError('无法确定交易日；请先生成候选池或交易日历')
    # 3) candidate pool
    _ensure_candidate_pool(python_exe, repo, session, d, trace)
    pool_path = repo / 'universe' / f'candidate_pool_{d}.csv'
    pool_df = pd.read_csv(pool_path)
    pool_codes = pool_df['ts_code'].astype(str).tolist()
    # 4) doctor + data gaps
    rep = _doctor(repo, session, d, d, trace)
    checks = rep.get('checks', {}) if rep else {}
    mincov = checks.get('min5_coverage', {})
    min_missing_map: Dict[str, List[str]] = {}
    if mincov and 'missing_pairs' in mincov:
        min_missing_map = {k: list(v) for k, v in (mincov.get('missing_pairs') or {}).items()}
    # Daily gaps by direct check
    daily_missing = _detect_daily_gaps(repo, d, pool_codes)
    # Try safe backfill
    if daily_missing:
        try:
            if session is not None:
                session.append('assistant', f"缺少日线数据 {len(daily_missing)} 支，将补齐当日快照。")
        except Exception:
            pass
        _fetch_daily_for_codes(repo, session, d, daily_missing, trace)
    # For minutes: prefer pool-only fetch
    if min_missing_map.get(d):
        try:
            if session is not None:
                session.append('assistant', f"分钟线缺口 {len(min_missing_map[d])} 支，尝试为候选池补齐5min。")
        except Exception:
            pass
        # Optional provider override from configs/config.yaml
        min_provider = None
        try:
            import yaml
            cfg = yaml.safe_load((repo / 'configs' / 'config.yaml').read_text(encoding='utf-8')) or {}
            min_provider = cfg.get('min_provider') or None
        except Exception:
            min_provider = None
        _fetch_min5_for_pool(repo, session, d, trace, min_provider=min_provider)
    # 5) rank
    provider = 'rule'
    ranked: List[Dict[str, Any]]
    raw = ''
    mode_param = mode if mode in ('auto','llm','rule') else 'auto'
    if mode_param in ('llm','auto'):
        try:
            provider, ranked, raw = _rank_llm(repo, session, d, template, topk, trace)
        except Exception:
            provider = 'fallback_rule'
            ranked = []
            raw = ''
    if provider in ('fallback_rule',) or mode_param == 'rule':
        # Deterministic rule-ranking (same as fallback)
        feats_rows = []
        prev_d = _last_trade_date_from_calendar(repo / 'data', d)
        for ts in pool_codes:
            df = _load_parquet(_daily_bar_path(repo / 'data', ts))
            df = df[df['trade_date'].astype(str) <= (prev_d or d)].sort_values('trade_date')
            if df.empty:
                continue
            close = df['close']
            row = {
                'ts_code': ts,
                'ret_5': float((close.iloc[-1] / close.iloc[-6]) - 1) if len(close) >= 6 else 0.0,
                'ret_20': float((close.iloc[-1] / close.iloc[-21]) - 1) if len(close) >= 21 else 0.0,
                'amt20': float(df['amount'].tail(20).mean() if 'amount' in df.columns else 0.0),
            }
            feats_rows.append(row)
        fdf = pd.DataFrame(feats_rows)
        sc = []
        for _, r in fdf.iterrows():
            s = float(r.get('ret_5', 0.0)) + 0.5 * float(r.get('ret_20', 0.0)) + 1e-12 * float(r.get('amt20', 0.0))
            sc.append((str(r['ts_code']), s))
        sc.sort(key=lambda x: x[1], reverse=True)
        ranked = [{'trade_date': d, 'rank': i+1, 'ts_code': ts, 'score': s, 'confidence': 0.4, 'reasons': 'fallback: rule-based', 'risk_flags': ''} for i,(ts,s) in enumerate(sc[:topk])]
        provider = 'fallback_rule'
    # Filter by exclusions / holdings if requested
    ranked = _mark_holdings_and_exclusions(ranked, positions, exclusions, no_holdings)
    # suggestions by cash (lot size 100)
    _suggest_qty(repo, d, ranked, cash)
    # 6) persist result
    out_dir = repo / 'store' / 'assistant' / 'picks'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f'pick_{d}_{template}_{mode_param}.json'
    digest = {'len': len(raw), 'sha256': (str(pd.util.hash_pandas_object(pd.DataFrame({'x':[raw]})).iloc[0]) if raw else '')}
    status = {
        'pool_ready': pool_path.exists(),
        'min5_missing': min_missing_map,
        'daily_missing': daily_missing,
    }
    # redact keys just in case
    safe_raw = re.sub(r"sk-[A-Za-z0-9]{4,}", "sk-***", raw or '')
    payload = {
        'date': d,
        'template': template,
        'topk': topk,
        'mode': mode_param,
        'provider': provider,
        'ranked_list': ranked,
        'raw_llm_output_digest': digest,
        'raw_llm_sample': safe_raw[:0],  # do not store payloads; keep empty per security
        'data_status_summary': status,
        'tool_trace_digest': trace,
    }
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return PickResult(date=d, topk=topk, template=template, mode=mode_param, provider=provider, ranked=ranked, data_status=status, out_file=out_file, trace=trace)
