"""Verify actual HTTP service; does not send any PayPal or Groq requests."""
import requests
import argparse

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',default='http://127.0.0.1:8000')
    args=parser.parse_args()
    with requests.Session() as s:
        root=args.base_url.rstrip('/')
        assert s.get(root,timeout=5).status_code==200
        assert s.get(root+'/health',timeout=5).json()['database']=='connected'
        assert s.get(root+'/sessions',timeout=5).status_code==401
        r=s.post(root+'/api/local-login',headers={'Origin':root},timeout=5)
        r.raise_for_status()
        for raw,expected in [('SELECT COUNT(*) AS n FROM shipments',600),('SELECT COUNT(*) AS n FROM ports',4)]:
            r=s.post(root+'/demo/query',json={'sql':raw},timeout=5)
            r.raise_for_status()
            assert r.json()['rows']==[{'n':expected}]
            assert r.json()['charged_cents']==0
        assert s.post(root+'/demo/query',json={'sql':'SELECT pg_sleep(10)'},timeout=5).status_code==422
        assert s.get(root+'/openapi.json',timeout=5).status_code==200
        sessions=s.get(root+'/sessions',timeout=5).json()
        for session in sessions:
            if session['state']!='settled': continue
            sid=session['id']
            queries=s.get(root+f'/sessions/{sid}/queries',timeout=5)
            queries.raise_for_status()
            charges=sum(q['result']['charged_cents'] for q in queries.json() if q['state']=='completed')
            assert charges==session['spent']
            runs=s.get(root+f'/sessions/{sid}/agent-runs',timeout=5)
            runs.raise_for_status()
            assert session['reserved']==0
            print('Persisted settled history checked:',len(queries.json()),'queries;',len(runs.json()),'agent runs;',charges,'cents. No queries replayed.')
    print('HTTP checks passed: built frontend, database health, access control, two real SQL results, malicious-query rejection, OpenAPI. No external payment or inference performed.')

if __name__=='__main__': main()
