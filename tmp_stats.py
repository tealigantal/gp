import sqlite3
from gp_assistant.core.paths import store_dir
DB=str(store_dir() / 'sessions' / 'session.db')
conn=sqlite3.connect(DB)
cur=conn.execute("SELECT count(*) FROM conv_messages WHERE author_id='assistant' AND kind='text' AND content LIKE ?", ('%抱歉%',))
print('guarded_failures', cur.fetchone()[0])
cur2=conn.execute("SELECT count(*) FROM conv_messages WHERE kind='card' AND payload LIKE '%\"type\": \"recommendation\"%'")
print('recommendation_cards', cur2.fetchone()[0])
conn.close()
#这个也是，怎么根目录会有这个
