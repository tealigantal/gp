import json, sqlite3
from pathlib import Path
p = Path('store')/ 'sessions' / 'session.db'
if not p.exists():
 print('no sessions db'); raise SystemExit
conn = sqlite3.connect(str(p))
cur = conn.execute("SELECT id, updated_at FROM conversations ORDER BY updated_at DESC, last_seq DESC LIMIT 1")
row = cur.fetchone()
if not row:
 print('no conv'); raise SystemExit
cid = row[0]
cur = conn.execute("SELECT id, seq_created, payload FROM conv_messages WHERE conversation_id=? AND kind='assistant_bundle' ORDER BY seq_created DESC LIMIT 5", (cid,))
rows = cur.fetchall()
print('conversation:', cid)
for r in rows:
  mid, seq, payload_json = r
  try:
    payload = json.loads(payload_json) if payload_json else {}
  except Exception:
    payload = {}
  rp = payload.get('right_panel') or {}
  tc = payload.get('tool_calls') or []
  print('seq', seq, 'run', rp.get('active_run_id'), 'reused', rp.get('reused_run'), 'reason', rp.get('refresh_reason'))
  for t in tc:
    nm = t.get('tool') or (t.get('function') or {}).get('name')
    args = t.get('args') or (t.get('function') or {}).get('arguments')
    print('  tool', nm, 'args', args)
