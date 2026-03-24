import json, sys, time
from pathlib import Path
root = Path.cwd(); sys.path.insert(0, str(root/'src'))
from gp_assistant.providers.akshare_provider import AkShareProvider
from gp_assistant.recommend.datahub import MarketDataHub

as_of = sys.argv[1]
p = AkShareProvider()
df, meta = p.spot_snapshot()
keep = []
for _,r in df.iterrows():
    code = str(r.get('code') or '')
    sym = str(r.get('symbol') or '')
    name = str(r.get('name') or '')
    if not (len(code)==6 and code.isdigit()):
        continue
    s = sym.lower()
    if s.startswith('bj'):
        continue
    if 'st' in name.lower():
        continue
    if s.startswith('sh'):
        if code.startswith('688') or code.startswith('689'):
            continue
    elif s.startswith('sz'):
        if code.startswith('300') or code.startswith('301'):
            continue
    else:
        continue
    keep.append(code)
keep = sorted(set(keep))
print(json.dumps({'as_of': as_of, 'count': len(keep), 'meta_source': (meta or {}).get('source')}, ensure_ascii=False))

hub = MarketDataHub()
ok=0; roll=0; tot=0; errs=[]
for s in keep:
    try:
        df2, meta2 = hub.daily_ohlcv(s, as_of=as_of, min_len=0, prefer_cache_only=False)
        tot += 1; ok += 1
        if bool((meta2 or {}).get('rollover_forced')):
            roll += 1
    except Exception as e:
        errs.append({'s': s, 'err': f'{type(e).__name__}: {e}'})
    if tot % 200 == 0:
        time.sleep(0.2)
print(json.dumps({'ok': True, 'as_of': as_of, 'total': tot, 'ok_count': ok, 'rollover_forced_count': roll, 'errors': errs[:10]}, ensure_ascii=False))
