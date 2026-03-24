import json, sqlite3
from gp_assistant.providers.factory import get_provider
from gp_assistant.search.history_store import canonical_query_id
from pathlib import Path

prov = get_provider()
name = getattr(prov, 'name', 'unknown')
qid = canonical_query_id({"kind":"daily","symbol":"600900","provider": name})
print('provider=', name, 'query_id=', qid)

p = Path('store')/ 'search' / 'history.db'
if not p.exists():
  print('history_db_missing')
  raise SystemExit
conn = sqlite3.connect(str(p))
cur = conn.execute("SELECT item_time, payload FROM items WHERE query_id=? ORDER BY item_time DESC LIMIT 1", (qid,))
row = cur.fetchone()
if not row:
  print('no_rows')
else:
  t, payload = row
  obj = json.loads(payload)
  print('latest_item_time=', t)
  print('latest_close=', obj.get('close'), 'date=', obj.get('date'))
