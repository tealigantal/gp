import json, sqlite3
from pathlib import Path

sess_db = Path('store') / 'sessions' / 'session.db'
if not sess_db.exists():
    print(json.dumps({"error": "session_db_missing", "path": str(sess_db)}))
    raise SystemExit

conn = sqlite3.connect(str(sess_db))
cur = conn.execute("SELECT id, updated_at FROM conversations ORDER BY updated_at DESC, last_seq DESC LIMIT 1")
row = cur.fetchone()
if not row:
    print(json.dumps({"error": "no_conversations"}))
    raise SystemExit
conv = row[0]
cur = conn.execute("SELECT id, seq_created, payload FROM conv_messages WHERE conversation_id=? AND kind='assistant_bundle' ORDER BY seq_created DESC LIMIT 5", (conv,))
rows = cur.fetchall() or []
out = []
for r in rows:
    pid = r[0]
    seq = int(r[1])
    try:
        payload = json.loads(r[2]) if r[2] else {}
    except Exception:
        payload = {}
    rp = payload.get('right_panel') or {}
    tools = payload.get('tool_calls') or []
    calls = []
    for t in tools:
        nm = t.get('tool') or (t.get('function') or {}).get('name') or t.get('name')
        args = t.get('args') or (t.get('function') or {}).get('arguments')
        calls.append({'name': nm, 'args': args})
    out.append({
        'message_id': pid,
        'seq': seq,
        'right_panel': {'active_run_id': rp.get('active_run_id'), 'tradeable': rp.get('tradeable'), 'run_gating': rp.get('run_gating'), 'refresh_reason': rp.get('refresh_reason'), 'reused_run': rp.get('reused_run')},
        'tool_calls': calls,
    })
print(json.dumps({'conversation_id': conv, 'bundles': out}, ensure_ascii=False))
