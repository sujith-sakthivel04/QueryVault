import json
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from app import app
from agent import research

def test_api_auth_and_free_synthetic_preview():
    c=TestClient(app,base_url='http://127.0.0.1:8000')
    assert c.get('/sessions').status_code==401
    assert c.post('/api/local-login',headers={'origin':'https://evil.example'}).status_code==403
    assert c.post('/api/local-login',headers={'origin':'http://127.0.0.1:8000'}).status_code==200
    r=c.post('/demo/query',json={'sql':'SELECT COUNT(*) AS n FROM shipments'})
    assert r.status_code==200 and r.json()['rows']==[{'n':600}]
    assert r.json()['charged_cents']==0
    assert c.post('/demo/query',json={'sql':'SELECT pg_sleep(30)'}).status_code==422
    assert c.get('/health').json()['database']=='connected'

def test_agent_affordability_replan_and_scope_guard():
    e=Mock()
    e.get.return_value={'budget':100,'spent':0,'reserved':0}
    e.quote.side_effect=[{'id':'q1','price':140,'sql':'SELECT COUNT(*) FROM shipments'}, {'id':'q2','price':35,'sql':'SELECT COUNT(*) FROM shipments'}]
    proposals=[{'sql':'SELECT COUNT(*) FROM shipments','reason':'same research objective','scope_changed':False}]*2
    replies=[SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(p)))]) for p in proposals]
    with patch.dict(os.environ,{'GROQ_API_KEY':'test-not-real'}),patch('agent.Groq') as groq:
        groq.return_value.chat.completions.create.side_effect=replies
        result=research(e,'sid','owner','Count all shipments in October 2026')
    assert len(result['decisions'])==2
    e.execute.assert_called_once_with('q2','owner')
    e.reset_mock()
    changed=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'scope_changed':True,'reason':'Only 7 days affordable'})))])
    with patch.dict(os.environ,{'GROQ_API_KEY':'test-not-real'}),patch('agent.Groq') as groq:
        groq.return_value.chat.completions.create.return_value=changed
        assert research(e,'sid','owner','30 day objective')['requires_approval'] is True
    e.execute.assert_not_called()

def test_no_key_never_calls_model_or_executes():
    e=Mock()
    with patch.dict(os.environ,{'GROQ_API_KEY':''}):
        assert research(e,'sid','owner','objective')['mode']=='offline'
    e.execute.assert_not_called()

def test_full_api_research_session_with_mock_paypal():
    from engine import Engine
    from test_engine import FakePayPal
    FakePayPal.voids=FakePayPal.captures=0
    FakePayPal.timeout=FakePayPal.mismatch=False
    c=TestClient(app,base_url='http://127.0.0.1:8000',headers={'X-API-Key':os.environ['LOCAL_API_KEY']})
    with patch('app.engine',Engine(FakePayPal)),patch('app.OWNER','test-api'):
        s=c.post('/sessions').json()
        sid=s['id']
        assert c.post(f'/sessions/{sid}/authorize').json()['state']=='authorized'
        assert c.post('/quote',json={'session_id':sid,'sql':'SELECT pg_sleep(10)'}).status_code==422
        total=0
        for raw in ('SELECT COUNT(*) FROM shipments','SELECT * FROM ports','SELECT * FROM routes'):
            q=c.post('/quote',json={'session_id':sid,'sql':raw}).json()
            r=c.post('/execute',json={'quote_id':q['id']})
            assert r.status_code==200
            total+=r.json()['charged_cents']
        settled=c.post(f'/sessions/{sid}/settle').json()
        assert settled['state']=='settled' and settled['spent']==total
        assert c.post(f'/sessions/{sid}/settle').json()['state']=='settled'
        assert FakePayPal.captures==1
        history=c.get(f'/sessions/{sid}/ledger').json()
        assert len([e for e in history if e['event']=='charged'])==3
        assert len([e for e in history if e['event']=='security_rejection'])==1
