"""Isolated deployment-style integration verification; no Docker/provider calls.

Creates a fresh synthetic-only cluster, migrates twice, launches the real
production entrypoint, checks HTTP boundaries/outage/restart, then stops only
its own services. Never reads operator .env or changes historical evidence.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid
import psycopg
import requests
from setup_local import executable

ROOT=Path(__file__).resolve().parent


def main():
    target=ROOT/'.local'/('deployment-check-'+uuid.uuid4().hex[:12])
    target.mkdir(parents=True)
    data=target/'pgdata'
    password=secrets.token_urlsafe(40)
    reader_password=secrets.token_urlsafe(40)
    report={'mode':'local production-entrypoint and fresh PostgreSQL verification; no cloud or Docker execution',
            'new_paypal_calls':0,'new_live_ai_calls':0,'checks':{}}
    env={k:v for k,v in os.environ.items() if not k.startswith(('QUERYVAULT_','PAYPAL_','GROQ_','DB_','MIGRATION_','READER_','PG')) and k not in ('DATABASE_URL','DATABASE_URL_FILE','LOCAL_API_KEY','PORT')}
    env.update(QUERYVAULT_MODE='public_demo',QUERYVAULT_PUBLIC_ORIGIN='http://127.0.0.1:8002',QUERYVAULT_DATASET='synthetic-logistics-v1',
               QUERYVAULT_HOST='127.0.0.1',PORT='8002',READER_DATABASE_URL=f'postgresql://qv_reader:{reader_password}@127.0.0.1:55434/queryvault')
    admin=dict(host='127.0.0.1',port=55434,user='postgres',password=password,connect_timeout=5)
    process=None;log=None;started=False
    def pg(action):
        subprocess.run([executable('pg_ctl'),'-D',str(data),'-l',str(target/'postgres.log'),'-w',action],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=True,timeout=30)
    def start_web():
        nonlocal process,log
        log=(target/'web.log').open('a',encoding='utf-8')
        process=subprocess.Popen([sys.executable,'serve.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
        for _ in range(100):
            if process.poll() is not None: raise RuntimeError('Production entrypoint exited')
            try:
                if requests.get('http://127.0.0.1:8002/health/ready',timeout=1).status_code==200:return
            except requests.RequestException:pass
            time.sleep(.1)
        raise RuntimeError('Production readiness timeout')
    def stop_web():
        nonlocal process,log
        if process is not None:
            process.terminate();process.wait(timeout=15);process=None
        if log is not None:log.close();log=None
    try:
        pw=target/'init-password'
        pw.write_text(password,encoding='utf-8')
        try:
            subprocess.run([executable('initdb'),'-D',str(data),'-U','postgres','-A','scram-sha-256','--pwfile',str(pw),'--encoding=UTF8','--locale=C'],check=True,capture_output=True)
        finally:pw.unlink(missing_ok=True)
        with (data/'postgresql.conf').open('a') as out:out.write("\nlisten_addresses='127.0.0.1'\nport=55434\nmax_connections=32\n")
        pg('start');started=True
        with psycopg.connect(**admin,autocommit=True) as c:c.execute('CREATE DATABASE queryvault')
        migration_env=env|{'MIGRATION_DATABASE_URL':f'postgresql://postgres:{password}@127.0.0.1:55434/queryvault','READER_DB_PASSWORD':reader_password}
        for _ in range(2):subprocess.run([sys.executable,'migrate_deployment.py'],cwd=ROOT,env=migration_env,check=True,capture_output=True)
        report['checks']['fresh_migration_and_repeatability']=True
        valid=subprocess.run([sys.executable,'serve.py','--check'],cwd=ROOT,env=env,capture_output=True)
        invalid=subprocess.run([sys.executable,'serve.py','--check'],cwd=ROOT,env=env|{'QUERYVAULT_PUBLIC_ORIGIN':''},capture_output=True)
        assert valid.returncode==0 and invalid.returncode==2
        assert reader_password not in (invalid.stdout+invalid.stderr).decode()
        report['checks']['production_config_validation_and_safe_failure']=True
        start_web();root='http://127.0.0.1:8002'
        with requests.Session() as client:
            def get(path,**kw):return client.get(root+path,timeout=8,**kw)
            def post(path,**kw):return client.post(root+path,timeout=8,**kw)
            assert get('/health/live').json()=={'status':'alive'}
            assert get('/api/config').json()['payments'] is False
            assert get('/health').json()['ai']=='disabled_in_public_demo'
            report['checks']['production_entrypoint_and_safe_health']=True
            for path in ('/','/buyer/research','/seller/ledger'):
                assert get(path).status_code==200,path
            for path in ('/.env','/app.py','/assets/missing.js','/api/unknown','/openapi.json'):
                assert get(path).status_code==404,path
            report['checks']['built_frontend_deep_links_and_api_404s']=True
            for method,path in [('POST','/api/local-login'),('POST','/sessions'),('GET','/sessions'),('GET','/sessions/private/ledger'),('POST','/sessions/private/authorize'),('POST','/sessions/private/settle'),('POST','/sessions/private/reconcile'),('POST','/sessions/private/recover-queries'),('POST','/quote'),('POST','/execute'),('POST','/agent'),('GET','/api/paypal/return-status?token=PRIVATE'),('GET','/paypal/return?token=PRIVATE')]:
                response=client.request(method,root+path,json={},timeout=8)
                assert response.status_code==403 and 'set-cookie' not in response.headers
            report['checks']['anonymous_operator_paypal_ai_and_private_data_denied']=True
            assert post('/demo/query',json={'sql':'SELECT * FROM shipments'}).status_code==422
            assert post('/demo/query',json={'template':'shipment_count','sql':'SELECT pg_sleep(5)'}).status_code==422
            assert post('/demo/query',json={'template':'shipment_count'},headers={'Origin':'https://evil.example'}).status_code==403
            assert post('/demo/query',json={'template':'shipment_count'},headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
            assert get('/health/live',headers={'Host':'evil.example'}).status_code==400
            assert post('/demo/query',data='x'*16385).status_code==413
            report['checks']['arbitrary_sql_origin_host_and_body_limits']=True
            count=post('/demo/query',json={'template':'shipment_count'});count.raise_for_status()
            assert count.json()['rows']==[{'shipment_count':600}] and count.json()['charged_cents']==0
            ports=post('/demo/query',json={'template':'port_delays'});ports.raise_for_status()
            assert len(ports.json()['rows'])==4 and ports.json()['charged_cents']==0
            assert 'Content-Security-Policy' in ports.headers
            report['checks']['two_real_fixed_read_only_templates_no_charge']=True
            evidence=get('/demo/evidence').json()
            assert evidence['captured_cents']==105 and 'HISTORICAL' in evidence['label']
            assert 'cases' not in get('/evaluation').json()
            report['checks']['sanitized_historical_evidence']=True
            stop_web();start_web()
            assert post('/demo/query',json={'template':'shipment_count'}).json()['rows']==[{'shipment_count':600}]
            report['checks']['web_restart_and_database_persistence']=True
            pg('stop');started=False
            assert get('/health/live').status_code==200
            assert get('/health/ready').status_code==503
            assert post('/demo/query',json={'template':'shipment_count'}).status_code==503
            pg('start');started=True
            assert get('/health/ready').status_code==200
            report['checks']['database_outage_and_recovery_without_web_restart']=True
        with psycopg.connect(**admin,dbname='queryvault') as c:
            for table in ('sessions','quotes','ledger','agent_runs'):
                assert c.execute('SELECT COUNT(*) FROM public.'+table).fetchone()[0]==0
            report['checks']['no_financial_or_agent_records_created']=True
            c.execute("INSERT INTO sessions(id,owner,state,budget,request_id) VALUES('migration-guard-fixture','deployment-test','created',2000,'no-provider-request')")
        refusal=subprocess.run([sys.executable,'migrate_deployment.py'],cwd=ROOT,env=migration_env,capture_output=True)
        assert refusal.returncode==1
        report['checks']['migration_refuses_existing_operator_records']=True
        report['passed']=all(report['checks'].values())
    except Exception as exc:
        report.update(passed=False,failure_type=type(exc).__name__)
        raise
    finally:
        stop_web()
        if started:pg('stop')
        (ROOT/'deployment-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
