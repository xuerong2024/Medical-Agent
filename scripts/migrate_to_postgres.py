"""Non-destructive migration: read the running H2-backed API, copy into the project PostgreSQL."""
import json
from pathlib import Path
import requests,psycopg
ROOT=Path(__file__).resolve().parents[1]
config=dict(line.split('=',1) for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines() if '=' in line and not line.lstrip().startswith('#'))
def get(path):
    r=requests.get('http://127.0.0.1:8080/api'+path,timeout=30);r.raise_for_status();return r.json()
tasks=get('/tasks');chunks=get('/knowledge')['chunks']
events={t['id']:get('/tasks/'+t['id']+'/events') for t in tasks}
backup={'tasks':tasks,'chunks':chunks,'events':events}
(ROOT/'.runtime'/'pre-postgres-migration.json').write_text(json.dumps(backup,ensure_ascii=False,indent=2),encoding='utf-8')
with psycopg.connect(host='127.0.0.1',port=55432,dbname='medagent',user='medagent',password=config['DB_PASSWORD']) as conn:
    conn.execute('CREATE TABLE IF NOT EXISTS analysis_task(id VARCHAR(36) PRIMARY KEY,created_at VARCHAR(40),payload TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS task_event(task_id VARCHAR(36),seq INTEGER,payload TEXT NOT NULL,PRIMARY KEY(task_id,seq))')
    conn.execute('CREATE TABLE IF NOT EXISTS knowledge_chunk(id VARCHAR(36) PRIMARY KEY,title VARCHAR(300),source VARCHAR(2000),body TEXT NOT NULL)')
    for t in tasks:
        conn.execute('INSERT INTO analysis_task VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING',(t['id'],t['createdAt'],json.dumps(t,ensure_ascii=False)))
        for e in events[t['id']]:conn.execute('INSERT INTO task_event VALUES(%s,%s,%s) ON CONFLICT(task_id,seq) DO NOTHING',(t['id'],e['seq'],json.dumps(e,ensure_ascii=False)))
    for c in chunks:conn.execute('INSERT INTO knowledge_chunk VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',(c['id'],c['title'],c['source'],c['text']))
print(json.dumps({'tasksCopied':len(tasks),'chunksCopied':len(chunks),'eventsCopied':sum(map(len,events.values())),'originalH2Preserved':True}))
