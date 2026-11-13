"""Verify the configured native PostgreSQL deployment without logging credentials."""
import json
from pathlib import Path
import requests,psycopg,nibabel as nib,numpy as np

ROOT=Path(__file__).resolve().parents[1]
config=dict(line.split('=',1) for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines() if '=' in line and not line.lstrip().startswith('#'))
BASE='http://127.0.0.1:8080/api'
def get(path,**params):
    r=requests.get(BASE+path,params=params,timeout=120);r.raise_for_status();return r.json()

health=get('/health');assert health['vectorEnabled'] is True
with psycopg.connect(host='127.0.0.1',port=55432,dbname='medagent',user='medagent',password=config['DB_PASSWORD']) as conn:
    version=conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
    vectors=conn.execute('SELECT count(*),min(vector_dims(embedding)),max(vector_dims(embedding)) FROM knowledge_vector').fetchone()
assert vectors[0]>=3 and vectors[1:]==(512,512),vectors
hits=get('/knowledge/search',query='肝脏体积如何计算')
assert any(h['title']=='体积计算与空间信息' for h in hits)
assert not get('/knowledge/search',query='zzzzunrelated82741')
chats=get('/conversations');assert chats
messages=get('/conversations/'+chats[0]['id'])['messages'];assert messages
image=nib.Nifti1Image(np.zeros((4,5,6),dtype=np.float32),np.diag([2.,2.,3.,1.]));image.header.set_xyzt_units('mm')
response=requests.post(BASE+'/files',files={'file':('public-synthetic-upload.nii',image.to_bytes(),'application/octet-stream')},timeout=30)
response.raise_for_status();assert response.json()['shape']==[4,5,6]
old=get('/tasks/151a88fd-3d5d-4c5d-b802-6d1436021ac5');assert old['status']=='SUCCEEDED' and old['result']['demo'] is False
result={'passed':True,'pgvectorVersion':version,'storedVectors':vectors[0],'dimensions':vectors[1],'relevantHits':[h['title'] for h in hits],
        'unrelatedQueryEmpty':True,'niiUploadViaJava':True,'oldRealInferencePreserved':True,'conversationCount':len(chats)}
(ROOT/'.runtime'/'chat-rag-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
