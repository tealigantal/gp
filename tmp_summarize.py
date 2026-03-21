import sqlite3, json
from gp_assistant.core.paths import store_dir
DB=str(store_dir() / 'sessions' / 'session.db')
conn=sqlite3.connect(DB)
conn.row_factory=sqlite3.Row
cur=conn.execute('SELECT id, title, updated_at, last_seq FROM conversations ORDER BY updated_at DESC LIMIT 6')
rows=cur.fetchall()
print('COUNT',len(rows))
for r in rows:
    cid=r['id']
    print('CID',cid,'updated',r['updated_at'],'last_seq',r['last_seq'])
    cur2=conn.execute('SELECT author_id, kind, content, payload, created_at FROM conv_messages WHERE conversation_id=? AND deleted_at IS NULL ORDER BY seq_created DESC LIMIT 6',(cid,))
    for rr in cur2.fetchall():
        content=(rr['content'] or '')[:120].replace('\n',' ')
        print('  -',rr['created_at'],rr['author_id'],rr['kind'],'|',content)
conn.close()

#这个是什么东西，怎么会在根目录里