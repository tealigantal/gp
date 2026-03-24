import os, sqlite3, json
from pathlib import Path
os.environ['PYTHONPATH']='/app/src'
from gp_assistant.core.paths import store_dir
p = store_dir() / 'sessions' / 'session.db'
conn = sqlite3.connect(str(p))
cur = conn.execute("SELECT id, updated_at FROM conversations ORDER BY updated_at DESC, last_seq DESC LIMIT 1")
row = cur.fetchone()
if not row:
  print(json.dumps({'error':'no_conversations'}))
  raise SystemExit
cid = row[0]
cur = conn.execute("SELECT id, seq_created, payload FROM conv_messages WHERE conversation_id=? AND kind='assistant_bundle' ORDER BY seq_created DESC LIMIT 5", (cid,))
rows = cur.fetchall() or []
out = []
for mid, seq, payload_json in rows:
  try:
    payload = json.loads(payload_json) if payload_json else {}
  except Exception:
    payload = {}
  rp = payload.get('right_panel') or {}
  tcs = payload.get('tool_calls') or []
  calls = []
  for t in tcs:
    nm = t.get('tool') or (t.get('function') or {}).get('name')
    args = t.get('args') or (t.get('function') or {}).get('arguments')
    calls.append({'tool': nm, 'args': args})
  out.append({'seq': int(seq), 'right_panel': {'active_run_id': rp.get('active_run_id'), 'refresh_reason': rp.get('refresh_reason'), 'reused_run': rp.get('reused_run')}, 'tool_calls': calls})
print(json.dumps({'cid': cid, 'bundles': out}, ensure_ascii=False))
