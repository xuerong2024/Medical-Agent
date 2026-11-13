"""Project-scoped PostgreSQL + pgvector. Bind only loopback, authenticated with SCRAM."""
import json,os,secrets,subprocess,sys
from pathlib import Path
import embedded_postgres

ROOT=Path(__file__).resolve().parents[1]
BIN=Path(embedded_postgres.__file__).parent/"pginstall"/"bin"
DATA=ROOT/"data"/"postgres-local"
ENV_FILE=ROOT/".env"
FLAGS=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
def run(name,*args,env=None,check=True):
    logfile=ROOT/'.runtime'/('pg-command-'+name+'.log')
    with logfile.open('w',encoding='utf-8') as output:
        result=subprocess.run([str(BIN/(name+'.exe' if os.name=='nt' else name)),*map(str,args)],env=env,creationflags=FLAGS,check=check,stdout=output,stderr=subprocess.STDOUT)
    result.stdout=logfile.read_text(encoding='utf-8',errors='replace')
    return result
def settings():
    return dict(line.split('=',1) for line in ENV_FILE.read_text(encoding='utf-8-sig').splitlines() if '=' in line and not line.lstrip().startswith('#'))
def update(values):
    old=ENV_FILE.read_text(encoding='utf-8-sig').splitlines();old=[l for l in old if l.split('=',1)[0] not in values]
    ENV_FILE.write_text('\n'.join(old+[k+'='+v for k,v in values.items()])+'\n',encoding='utf-8')
def start():
    config=settings();password=config.get('DB_PASSWORD') or secrets.token_urlsafe(24)
    update({'DB_PASSWORD':password})
    if not (DATA/'PG_VERSION').exists():
        DATA.mkdir(parents=True,exist_ok=True);pw=ROOT/'.runtime'/'pg-init-password'
        pw.write_text(password,encoding='utf-8')
        try:
            result=run('initdb','-D',DATA,'-U','medagent','--encoding=UTF8','--locale=C','--auth-host=scram-sha-256','--auth-local=scram-sha-256','--pwfile',pw)
        finally:pw.unlink(missing_ok=True)
    if run('pg_ctl','-D',DATA,'status',check=False).returncode!=0:
        run('pg_ctl','-D',DATA,'-l',ROOT/'.runtime'/'postgres.log','-o','-h 127.0.0.1 -p 55432','-w','start')
    env=dict(os.environ,PGPASSWORD=password)
    exists=run('psql','-h','127.0.0.1','-p','55432','-U','medagent','-d','postgres','-tAc',"SELECT 1 FROM pg_database WHERE datname='medagent'",env=env).stdout.strip()
    if exists!='1':run('createdb','-h','127.0.0.1','-p','55432','-U','medagent','medagent',env=env)
    run('psql','-h','127.0.0.1','-p','55432','-U','medagent','-d','medagent','-c','CREATE EXTENSION IF NOT EXISTS vector',env=env)
    update({'DB_URL':'jdbc:postgresql://127.0.0.1:55432/medagent','DB_USER':'medagent','DB_PASSWORD':password,'LOCAL_POSTGRES':'true',
            'VECTOR_ENABLED':'true','EMBEDDING_BASE_URL':'http://127.0.0.1:8090','EMBEDDING_API_KEY':'local','EMBEDDING_MODEL':'BAAI/bge-small-zh-v1.5'})
    print('Project PostgreSQL + pgvector ready on 127.0.0.1:55432')
if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='stop':
        if (DATA/'PG_VERSION').exists():run('pg_ctl','-D',DATA,'-m','fast','stop',check=False)
    else:start()
