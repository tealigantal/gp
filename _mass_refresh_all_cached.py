import json, sqlite3, sys
from datetime import datetime
from pathlib import Path

root = Path.cwd(); sys.path.insert(0, str(root/'src'))
from gp_assistant.recommend.datahub import MarketDataHub

db = Path('store/search/history.db')
syms = []
if db.exists():
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute('SELECT params FROM queries')
        seen=set()
        for (pjson,) in cur.fetchall():
            try:
                p = json.loads(pjson)
                if p.get('kind')=='daily':
                    s = str(p.get('symbol') or '').strip()
                    if s and s not in seen:
                        seen.add(s)
                        syms.append(s)
            except Exception:
                continue
    finally:
        conn.close()

hub = MarketDataHub()
as_of = datetime.now().date().isoformat()
summary=[]
for s in syms:
    try:
        df, meta = hub.daily_ohlcv(s, as_of=as_of, min_len=0, prefer_cache_only=False)
        summary.append({'s': s, 'ok': True, 'roll': bool((meta or {}).get('rollover_forced')), 'rows_new': (meta or {}).get('rows_new')})
    except Exception as e:
        summary.append({'s': s, 'ok': False, 'err': f'{type(e).__name__}: {e}'})

roll_ct = sum(1 for r in summary if r.get('ok') and r.get('roll'))
errs = [r for r in summary if not r.get('ok')]
print(json.dumps({'ok': True, 'n': len(summary), 'rollover_forced_count': roll_ct, 'errors': errs[:5]}, ensure_ascii=False))
