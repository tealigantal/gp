import sqlite3, json
from gp_assistant.core.paths import store_dir
DB=str(store_dir() / 'sessions' / 'session.db')
conn=sqlite3.connect(DB)
conn.row_factory=sqlite3.Row
cur=conn.execute("SELECT conversation_id, seq_created, payload FROM conv_messages WHERE kind='assistant_bundle' ORDER BY created_at DESC LIMIT 1")
row=cur.fetchone()
if not row:
    print('no_assistant_bundle')
else:
    cid=row['conversation_id']; seq=row['seq_created']; payload=json.loads(row['payload'] or '{}')
    print('cid',cid,'seq',seq)
    tc=payload.get('tool_calls') or []
    tr=payload.get('tool_results') or []
    print('tool_calls', json.dumps(tc, ensure_ascii=False))
    if tr:
        print('first_tool_result', json.dumps(tr[0], ensure_ascii=False)[:500])
#这个也是，怎么在根目录里