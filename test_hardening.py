from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from types import SimpleNamespace
import json
import os
import pytest
import psycopg
from fastapi.testclient import TestClient
from app import app
from db import connect,read_query
from engine import Engine,Conflict
from firewall import QueryFirewall,PolicyError
from agent import research
from test_engine import FakePayPal,authorized

@pytest.fixture
def engine():
    FakePayPal.captures=FakePayPal.voids=0
    FakePayPal.timeout=FakePayPal.mismatch=False
    return Engine(FakePayPal)

def test_closed_or_unknown_session_cannot_reach_planner(engine):
    sid=authorized(engine)
    with connect() as c: c.execute("UPDATE sessions SET state='settling' WHERE id=%s",(sid,))
    with patch('engine.read_query') as reader:
        for target,owner in ((sid,'test'),(sid,'wrong'),('missing','test')):
            with pytest.raises(Conflict): engine.quote(target,owner,'SELECT * FROM ports')
        reader.assert_not_called()

@pytest.mark.parametrize('field,value',[('price',140),('version','changed'),('sql_hash','0'*64)])
def test_quote_commercial_tampering_is_not_executable(engine,field,value):
    from psycopg import sql
    sid=authorized(engine);q=engine.quote(sid,'test','SELECT * FROM ports')
    with connect() as c: c.execute(sql.SQL('UPDATE quotes SET {}=%s WHERE id=%s').format(sql.Identifier(field)),(value,q['id']))
    with patch('engine.read_query') as reader:
        with pytest.raises(Conflict): engine.execute(q['id'],'test')
        reader.assert_not_called()
    assert engine.get(sid,'test')['spent']==0

def test_signature_is_timezone_independent(engine):
    from datetime import timezone
    from engine import binding_signature
    sid=authorized(engine);q=engine.quote(sid,'test','SELECT * FROM ports')
    other={**q,'expires_at':q['expires_at'].astimezone(timezone.utc)}
    assert binding_signature(other)==q['binding_signature']

def test_inconsistent_ledger_fails_closed_before_payment(engine):
    sid=authorized(engine);q=engine.quote(sid,'test','SELECT * FROM ports')
    engine.execute(q['id'],'test')
    with connect() as c: c.execute('UPDATE sessions SET spent=34 WHERE id=%s',(sid,))
    assert engine.settle(sid,'test')['state']=='reconciliation_required'
    assert FakePayPal.captures==FakePayPal.voids==0
    with pytest.raises(Conflict): engine.quote(sid,'test','SELECT * FROM ports')
    with pytest.raises(Conflict): engine.reconcile(sid,'test')

def test_explicit_accepted_ceiling_and_hash(engine):
    sid=authorized(engine);q=engine.quote(sid,'test','SELECT * FROM ports')
    with pytest.raises(Conflict): engine.execute(q['id'],'test',max_price_cents=34)
    with pytest.raises(Conflict): engine.execute(q['id'],'test',sql_hash='0'*64)
    result=engine.execute(q['id'],'test',max_price_cents=35,sql_hash=q['sql_hash'])
    assert result['charged_cents']==35
    assert engine.execute(q['id'],'test',max_price_cents=35,sql_hash=q['sql_hash'])==result

def test_settlement_drains_running_query_and_blocks_new_admission(engine):
    sid=authorized(engine)
    q=engine.quote(sid,'test','SELECT * FROM ports')
    other=engine.quote(sid,'test','SELECT * FROM routes')
    entered,release=Event(),Event()
    def slow_query(_):
        entered.set()
        assert release.wait(10)
        return [{'name':'Synthetic result'}]
    with ThreadPoolExecutor(max_workers=1) as pool:
        with patch('engine.read_query',side_effect=slow_query):
            future=pool.submit(engine.execute,q['id'],'test')
            assert entered.wait(10)
            try:
                assert engine.settle(sid,'test')['waiting_for_queries']
                assert FakePayPal.captures==0
                with pytest.raises(Conflict): engine.execute(other['id'],'test')
                with pytest.raises(Conflict): engine.quote(sid,'test','SELECT * FROM ports')
            finally: release.set()
            assert future.result(timeout=10)['charged_cents']==35
    assert engine.settle(sid,'test')['state']=='settled'
    assert FakePayPal.captures==1

def test_parallel_repeated_quote_charges_once(engine):
    sid=authorized(engine);q=engine.quote(sid,'test','SELECT * FROM ports')
    def run(_):
        try: return engine.execute(q['id'],'test')
        except Conflict: return None
    with ThreadPoolExecutor(max_workers=8) as pool: results=list(pool.map(run,range(12)))
    assert any(results)
    assert engine.get(sid,'test')['spent']==35
    assert len([e for e in engine.ledger(sid,'test') if e['event']=='charged'])==1

def test_recovery_fences_late_worker_without_double_release_or_charge(engine):
    sid=authorized(engine);q=engine.quote(sid,'test','SELECT * FROM ports')
    entered,release=Event(),Event()
    def blocked(_):
        entered.set()
        assert release.wait(10)
        return [{'name':'Result must not be delivered'}]
    with ThreadPoolExecutor(max_workers=1) as pool,patch('engine.read_query',side_effect=blocked):
        future=pool.submit(engine.execute,q['id'],'test')
        assert entered.wait(10)
        try:
            assert engine.recover_stale_queries(sid,'test')['recovered_queries']==0
            with connect() as c: c.execute("UPDATE quotes SET started_at=now()-interval '1 hour' WHERE id=%s",(q['id'],))
            recovered=engine.recover_stale_queries(sid,'test')
            assert recovered['released_cents']==35 and recovered['payments_attempted']==0
            assert engine.recover_stale_queries(sid,'test')['recovered_queries']==0
        finally: release.set()
        with pytest.raises(Conflict): future.result(timeout=10)
    assert engine.get(sid,'test')['spent']==engine.get(sid,'test')['reserved']==0
    assert not [e for e in engine.ledger(sid,'test') if e['event']=='charged']

def test_reader_rejects_raw_attack_before_connection():
    with patch('db.connect') as connection:
        with pytest.raises(PolicyError): read_query('SELECT pg_read_file(\'/etc/passwd\')')
        connection.assert_not_called()

def test_reader_grants_and_database_timeout():
    with connect(True) as c:
        row=c.execute("SELECT has_database_privilege(current_user,current_database(),'TEMP') AS temp,has_table_privilege(current_user,'public.sessions','SELECT') AS app_read,has_schema_privilege(current_user,'public','CREATE') AS create_public").fetchone()
        assert row=={'temp':False,'app_read':False,'create_public':False}
        c.execute("SET LOCAL statement_timeout='50ms'")
        with pytest.raises(psycopg.errors.QueryCanceled): c.execute('SELECT pg_sleep(0.2)')

def test_analytics_date_functions_and_expensive_plan():
    safe=QueryFirewall().validate("SELECT DATE_TRUNC('month',shipped_on) AS month,COUNT(*) AS n FROM shipments GROUP BY 1")
    assert read_query(safe)[0]['n']==600
    with pytest.raises(PolicyError): read_query('SELECT COUNT(*) FROM shipments a JOIN shipments b ON TRUE JOIN shipments c ON TRUE')

def test_agent_cannot_silently_shrink_scope(engine):
    sid=authorized(engine)
    proposals=[{'sql':"SELECT COUNT(*) FROM shipments WHERE shipped_on >= '2026-10-01'",'reason':'30 day objective','scope_changed':False},{'sql':"SELECT COUNT(*) FROM shipments WHERE shipped_on >= '2026-10-24'",'reason':'Cheaper seven day subset','scope_changed':False}]
    replies=[SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(p)))]) for p in proposals]
    with patch.dict(os.environ,{'GROQ_API_KEY':'mock-key'}),patch('agent.Groq') as groq,patch.object(engine,'get',return_value={'budget':20,'spent':0,'reserved':0}),patch.object(engine,'execute') as execute:
        groq.return_value.chat.completions.create.side_effect=replies
        result=research(engine,sid,'test','Research the full month of October')
    assert result['requires_approval']
    execute.assert_not_called()

def test_api_history_and_durable_agent_run_with_mock_inference(engine):
    sid=authorized(engine)
    q=engine.quote(sid,'test','SELECT * FROM ports')
    engine.execute(q['id'],'test')
    c=TestClient(app,base_url='http://127.0.0.1:8000',headers={'X-API-Key':os.environ['LOCAL_API_KEY']})
    with patch('app.engine',engine),patch('app.OWNER','test'):
        assert c.get(f'/sessions/{sid}/queries').json()[0]['result']['rows']
        result={'mode':'mock_inference','decisions':[{'reason':'mocked decision','price_cents':35}]}
        with patch('app.research',return_value=result):
            r=c.post('/agent',json={'session_id':sid,'objective':'Count all shipments'})
        assert r.status_code==200
        runs=c.get(f'/sessions/{sid}/agent-runs').json()
        assert runs[0]['result']['mode']=='mock_inference'
        with patch('app.research',side_effect=RuntimeError('injected model timeout')):
            assert c.post('/agent',json={'session_id':sid,'objective':'Count all shipments'}).status_code==502
        assert c.get(f'/sessions/{sid}/agent-runs').json()[0]['state']=='failed'
    with pytest.raises(Conflict): engine.history(sid,'someone-else')
