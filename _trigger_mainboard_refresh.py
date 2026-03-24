import json, sys, time
from pathlib import Path
root = Path.cwd(); sys.path.insert(0, str(root/'src'))
from gp_assistant.providers.akshare_provider import AkShareProvider
from gp_assistant.recommend.datahub import MarketDataHub

as_of = sys.argv[1]
p = AkShareProvider()
df, meta = p.spot_snapshot()
# Filters: exclude ST; mainboard approximated: sh non-688/689; sz non-300/301; exclude bj
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
        # otherwise keep
    elif s.startswith('sz'):
        if code.startswith('300') or code.startswith('301'):
            continue
        # otherwise keep
    else:
        continue
    keep.append(code)
keep = sorted(set(keep))
print(json.dumps({'as_of': as_of, 'count': len(keep), 'sample': keep[:10], 'meta_source': (meta or {}).get('source')}, ensure_ascii=False))
# Batch refresh
hub = MarketDataHub()
batch=200
ok=0; roll=0; tot=0
for i in range(0, len(keep), batch):
    chunk = keep[i:i+batch]
    res = hub.daily_ohlcv_batch(chunk, as_of=as_of, safety_lookback_days=2)
    for s,(df2,meta2) in res.items():
        tot += 1
        ok += 1
        if bool((meta2 or {}).get('rollover_forced')):
            roll += 1
    time.sleep(0.2)
print(json.dumps({'ok': True, 'as_of': as_of, 'total': tot, 'ok_count': ok, 'rollover_forced_count': roll}, ensure_ascii=False))
