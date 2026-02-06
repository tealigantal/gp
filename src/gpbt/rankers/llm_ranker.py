from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd
from jsonschema import validate, ValidationError

from ..config import AppConfig
from ..llm.deepseek_client import DeepseekClient, LLMConfig
from ..storage import load_parquet, daily_bar_path


PICKS_SCHEMA = {
    "type": "object",
    "required": ["date", "template_id", "picks"],
    "properties": {
        "date": {"type": "string"},
        "template_id": {"type": "string"},
        "picks": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["ts_code", "score", "confidence", "reasons", "risk_flags"],
                "properties": {
                    "ts_code": {"type": "string"},
                    "score": {"type": "number"},
                    "confidence": {"type": "number"},
                    "reasons": {"type": "array", "items": {"type": "string"}},
                    "risk_flags": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def _load_llm_cfg() -> LLMConfig:
    import yaml
    p = Path('configs/llm.yaml')
    data = yaml.safe_load(p.read_text(encoding='utf-8')) if p.exists() else {}
    return LLMConfig(
        provider=data.get('provider', 'deepseek'),
        base_url=str(data.get('base_url', 'https://api.deepseek.com/v1')),
        model=str(data.get('model', 'deepseek-chat')),
        api_key_env=str(data.get('api_key_env', 'DEEPSEEK_API_KEY')),
        temperature=float(data.get('temperature', 0)),
        max_tokens=int(data.get('max_tokens', 1200)),
        timeout_sec=int(data.get('timeout_sec', 60)),
        retries=int(data.get('retries', 2)),
        json_mode=bool(data.get('json_mode', True)),
    )


def _load_template(template_id: str) -> Dict:
    import yaml
    path = Path('configs/llm_templates') / f'{template_id}.yaml'
    if not path.exists():
        raise RuntimeError(f"LLM template not found: {path}")
    return yaml.safe_load(path.read_text(encoding='utf-8')) or {}


def _prev_trade_date(cfg: AppConfig, date: str) -> str:
    cal = load_parquet(cfg.paths.data_root / 'raw' / 'trade_cal.parquet')
    if cal.empty:
        raise RuntimeError('trade_cal missing; run fetch first')
    arr = cal['trade_date'].astype(str).tolist()
    arr = [d for d in arr if d < date]
    if not arr:
        raise RuntimeError('no previous trade date')
    return sorted(arr)[-1]


def _features_for_codes(cfg: AppConfig, codes: List[str], end_date: str) -> pd.DataFrame:
    rows = []
    for ts in codes:
        df = load_parquet(daily_bar_path(cfg.paths.data_root, ts))
        if df.empty:
            continue
        df = df[df['trade_date'] <= end_date].sort_values('trade_date')
        if df.empty:
            continue
        close = df['close']
        row = {
            'ts_code': ts,
            'last_close': float(close.iloc[-1]),
            'ret_5': float((close.iloc[-1] / close.iloc[-6]) - 1) if len(close) >= 6 else 0.0,
            'ret_20': float((close.iloc[-1] / close.iloc[-21]) - 1) if len(close) >= 21 else 0.0,
            'amt20': float(df['amount'].tail(20).mean() if 'amount' in df.columns else 0.0),
            'vol20': float(df['vol'].tail(20).mean() if 'vol' in df.columns else 0.0),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def rank(cfg: AppConfig, date: str, template_id: str, force: bool = False, topk: int = 3) -> pd.DataFrame:
    # Preconditions
    cand_path = cfg.paths.universe_root / f"candidate_pool_{date}.csv"
    if not cand_path.exists():
        raise RuntimeError(f"candidate pool missing: {cand_path}")
    cands_df = pd.read_csv(cand_path)
    if len(cands_df) != 20:
        raise RuntimeError(f"candidate pool must be 20 rows, got {len(cands_df)}")
    pool = cands_df['ts_code'].astype(str).tolist()

    # Cache paths
    cache_in = cfg.paths.data_root / 'llm_cache' / 'inputs' / f'date={date}'
    cache_out = cfg.paths.data_root / 'llm_cache' / 'outputs' / f'date={date}'
    cache_in.mkdir(parents=True, exist_ok=True)
    cache_out.mkdir(parents=True, exist_ok=True)
    in_file = cache_in / f'template={template_id}.json'
    out_file = cache_out / f'template={template_id}.json'
    ranked_out = cfg.paths.universe_root / f'candidate_pool_{date}_ranked_{template_id}.csv'

    # If cached outputs exist and not forcing, return parsed ranked csv if present
    if out_file.exists() and ranked_out.exists() and not force:
        return pd.read_csv(ranked_out)

    # Build features up to prev trade date
    prev_d = _prev_trade_date(cfg, date)
    feats = _features_for_codes(cfg, pool, prev_d)
    if feats.empty:
        raise RuntimeError('no features available before date')

    # Load prompt template
    tmpl = _load_template(template_id)
    system_prompt = tmpl.get('system_prompt', '')
    user_payload = {
        'date': date,
        'template_id': template_id,
        'pool': pool,
        'features': feats.to_dict(orient='records'),
        'schema': PICKS_SCHEMA,
        'requirements': [
            '只允许从候选池 pool 中选择，严格输出3个对象',
            '必须返回JSON且满足schema，不得附加文字',
            '不得使用当日盘中或收盘后的信息',
        ],
    }
    in_file.write_text(json.dumps(user_payload, ensure_ascii=False, indent=2), encoding='utf-8')

    # Call LLM with provider-aware fallback
    llm_cfg = _load_llm_cfg()
    provider = llm_cfg.provider.lower()
    data = None
    if provider == 'mock':
        # Deterministic mock: score by simple linear combo and keep pool order deterministic
        feats = feats.sort_values('ts_code')  # stable
        sc = []
        for _, r in feats.iterrows():
            s = float(r.get('ret_5', 0.0)) + 0.5 * float(r.get('ret_20', 0.0)) + 1e-12 * float(r.get('amt20', 0.0))
            sc.append((str(r['ts_code']), s))
        sc.sort(key=lambda x: x[1], reverse=True)
        picks = []
        for ts, s in sc[:topk]:
            picks.append({
                'ts_code': ts,
                'score': float(s),
                'confidence': 0.5,
                'reasons': ["mock: momentum score (no LLM)"],
                'risk_flags': []
            })
        data = {'date': date, 'template_id': template_id, 'picks': picks, '_provider': 'mock'}
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        try:
            client = DeepseekClient(llm_cfg)
            resp = client.chat([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
            ])
            text = resp.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            out_file.write_text(text, encoding='utf-8')
            try:
                data = json.loads(text)
            except Exception as e:
                raise RuntimeError(f'LLM output is not valid JSON: {e}\n{text}')
        except Exception as e:
            # Do not perform any rule-based fallback here.
            # Let the higher-level assistant fall back to mock provider.
            raise RuntimeError(f'LLM ranking failed: {e}')

    # Validate schema
    try:
        validate(data, PICKS_SCHEMA)
    except ValidationError as e:
        raise RuntimeError(f'LLM output violates schema: {e.message}')

    # Enforce pool membership and uniqueness and exact topk
    picks = data['picks']
    if len(picks) != topk:
        raise RuntimeError(f'LLM must return exactly {topk} picks')
    seen = set()
    for p in picks:
        ts = str(p['ts_code'])
        if ts not in pool:
            raise RuntimeError(f'pick {ts} not in candidate pool')
        if ts in seen:
            raise RuntimeError(f'duplicate pick {ts}')
        seen.add(ts)

    # Overwrite raw with pretty JSON after validation
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    # Build ranked csv
    rows = []
    for i, p in enumerate(picks, start=1):
        rows.append({
            'trade_date': date,
            'rank': i,
            'ts_code': p['ts_code'],
            'score': p.get('score', 0.0),
            'confidence': p.get('confidence', 0.0),
            'reasons': ';'.join(p.get('reasons', [])),
            'risk_flags': ';'.join(p.get('risk_flags', [])),
        })
    rdf = pd.DataFrame(rows)
    rdf.to_csv(ranked_out, index=False, encoding='utf-8')
    return rdf
