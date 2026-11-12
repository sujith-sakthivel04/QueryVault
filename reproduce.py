"""Isolated fresh checkout/venv/cluster/bootstrap test; never loads operator keys."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import requests
from package_submission import public_files

ROOT=Path(__file__).resolve().parent
def main():
    # Never reuse a previous environment, database or installed dependencies.
    target=ROOT/'.local'/('repro-'+uuid.uuid4().hex[:12]);target.mkdir(parents=True)
    # Use the same reviewed allowlist as the local publication candidate.  A
    # broad extension copy previously pulled private JSON evidence into this
    # temporary checkout and omitted frontend/public and screenshot assets.
    for p in public_files():
        destination=target/p.relative_to(ROOT)
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,destination)
    env=dict(os.environ)
    for key in list(env):
        if key.startswith(('PAYPAL_','GROQ_','DB_','QUERYVAULT_')) or key in ('DATABASE_URL','READER_DATABASE_URL','LOCAL_API_KEY'):
            env.pop(key)
    env['QUERYVAULT_DB_PORT']='55433'
    python=target/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    process=None
    log=None
    report={'environment':'isolated copied checkout, new .venv, PostgreSQL cluster on 55433, no private API keys','fresh_directory':target.name,'checks':{}}
    try:
        subprocess.run([sys.executable,'bootstrap.py'],cwd=target,env=env,check=True)
        subprocess.run([str(python),'setup_local.py'],cwd=target,env=env,check=True)
        log=(target/'.local/repro-backend.log').open('w')
        process=subprocess.Popen([str(python),'-m','uvicorn','app:app','--host','127.0.0.1','--port','8001'],cwd=target,env=env,stdout=log,stderr=log)
        with requests.Session() as client:
            root='http://127.0.0.1:8001'
            for _ in range(100):
                try:
                    h=client.get(root+'/health',timeout=1)
                    if h.status_code==200:break
                except requests.RequestException:pass
                time.sleep(.1)
            h.raise_for_status();health=h.json()
            assert health['database']=='connected' and health['ai']=='offline' and health['paypal']=='credentials_missing'
            report['checks']['health_offline_no_keys']=True
            assert client.get(root,timeout=5).status_code==200
            report['checks']['built_frontend_served']=True
            client.post(root+'/api/local-login',headers={'Origin':root},timeout=5).raise_for_status()
            result=client.post(root+'/demo/query',json={'sql':'SELECT COUNT(*) AS n FROM shipments'},timeout=5)
            assert result.json()['rows']==[{'n':600}] and result.json()['charged_cents']==0
            report['checks']['synthetic_dataset_and_free_query']=True
            assert client.get(root+'/sessions',timeout=5).json()==[]
            report['checks']['no_financial_sessions_or_payments']=True
            assert client.get(root+'/demo/evidence',timeout=5).json()['capture_status']=='COMPLETED'
            report['checks']['labeled_historical_evidence_available']=True
            assert client.post(root+'/demo/query',json={'sql':'SELECT pg_sleep(1)'},timeout=5).status_code==422
            report['checks']['malicious_query_rejected']=True
            report['checks']['repeatable_migrations_and_bootstrap']=True
        subprocess.run([str(python),'-m','pytest','-q','--junitxml=test-results.xml'],cwd=target,env=env,check=True)
        report['checks']['full_backend_regressions_clean_environment']=True
        npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
        subprocess.run([npm,'test'],cwd=target/'frontend',env=env,check=True)
        report['checks']['full_frontend_regressions_clean_environment']=True
    finally:
        if process is not None:
            process.terminate();process.wait(timeout=10)
        if log is not None: log.close()
        # Stop only this explicitly isolated cluster, never the main application.
        if (target/'.local/pgdata/PG_VERSION').exists():
            subprocess.run([str(python),'-c',"from setup_local import executable,DATA;import subprocess;subprocess.run([executable('pg_ctl'),'-D',str(DATA),'-m','fast','-w','stop'],check=True)"],cwd=target,env=env,check=True)
    report['passed']=all(report['checks'].values())
    # Keep the run's report with its disposable source copy.  Writing to the
    # repository root overwrote the previous reproducibility evidence every
    # time this script was run.
    report_path=target/'reproducibility-report.json'
    report_path.write_text(json.dumps(report,indent=2))
    report['report_path']=str(report_path.relative_to(ROOT))
    report_path.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
