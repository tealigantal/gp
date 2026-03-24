import os, sqlite3, json
os.environ['PYTHONPATH']='/app/src'
from gp_assistant.core.paths import store_dir
p = store_dir() / 'sessions' / 'session.db'
conn = sqlite3.connect(str(p))
cur = conn.execute("SELECT id, seq_created, payload FROM conv_messages WHERE conversation_id=? AND kind='assistant_bundle' ORDER BY seq_created DESC LIMIT 5", (os.environ.get('CID'),))
rows = cur.fetchall()
for mid, seq, payload_json in rows:
    try:
        payload = json.loads(payload_json) if payload_json else {}
    except Exception:
        payload = {}
    rp = payload.get('right_panel') or {}
    tcs = payload.get('tool_calls') or []
    print('seq', seq, 'run', rp.get('active_run_id'), 'reused', rp.get('reused_run'), 'reason', rp.get('refresh_reason'))
    for t in tcs:
        nm = t.get('tool') or (t.get('function') or {}).get('name')
        args = t.get('args') or (t.get('function') or {}).get('arguments')
        print('  tool', nm, 'args', args)
