import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
from agent import research
from demo_economics import NonBillingBroker,render_report,main
from engine import Conflict

def reply(sql,reason,scope_changed=False):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'sql':sql,'reason':reason,'scope_changed':scope_changed})))])

def test_over_budget_refusal_gets_one_bounded_requote_chance():
    e=Mock();e.get.return_value={'budget':50,'spent':0,'reserved':0}
    sql="SELECT COUNT(*) FROM shipments WHERE shipped_on >= '2026-10-01'"
    e.quote.side_effect=[{'id':'q1','price':70,'sql':sql},{'id':'q2','price':70,'sql':sql}]
    with patch.dict(os.environ,{'GROQ_API_KEY':'mock-only'}),patch('agent.Groq') as model:
        model.return_value.chat.completions.create.side_effect=[reply(sql,'Full scope'),reply('','No alternative',True),reply(sql,'Original plan requote; no savings')]
        out=research(e,'evaluation','owner','Keep the full month')
    assert out['refused'] is True
    assert [a['outcome'] for a in out['attempts']]==['over_budget','no_alternative_proposed','over_budget']
    assert e.quote.call_count==2
    e.execute.assert_not_called()

def test_scope_changed_candidate_is_never_forced_to_execute():
    e=Mock();e.get.return_value={'budget':50,'spent':0,'reserved':0}
    sql="SELECT COUNT(*) FROM shipments WHERE shipped_on >= '2026-10-01'"
    with patch.dict(os.environ,{'GROQ_API_KEY':'mock-only'}),patch('agent.Groq') as model:
        e.quote.return_value={'id':'q1','price':70,'sql':sql}
        model.return_value.chat.completions.create.side_effect=[reply(sql,'Full month'),reply("SELECT COUNT(*) FROM shipments WHERE shipped_on >= '2026-10-24'",'Shorter timeframe',True)]
        out=research(e,'evaluation','owner','Keep the full month')
    assert out['requires_approval'] is True
    e.execute.assert_not_called()

@pytest.mark.parametrize('changed',[
    'SELECT MAX(delay_hours) FROM shipments',
    'SELECT AVG(delay_hours) FROM shipments ORDER BY 1 DESC',
    'SELECT AVG(delay_hours) FROM shipments LIMIT 1',
    'SELECT DISTINCT AVG(delay_hours) FROM shipments',
])
def test_model_cannot_change_output_semantics_while_claiming_unchanged_scope(changed):
    e=Mock();e.get.return_value={'budget':50,'spent':0,'reserved':0}
    original='SELECT AVG(delay_hours) FROM shipments'
    e.quote.side_effect=[{'id':'q1','price':70,'sql':original},{'id':'q2','price':35,'sql':changed}]
    with patch.dict(os.environ,{'GROQ_API_KEY':'mock-only'}),patch('agent.Groq') as model:
        model.return_value.chat.completions.create.side_effect=[reply(original,'Original question'),reply(changed,'Claims same scope')]
        out=research(e,'evaluation','owner','Average delay over all shipments')
    assert out['requires_approval'] is True
    assert out['attempts'][-1]['outcome']=='scope_review'
    e.execute.assert_not_called()

def test_nonbilling_broker_blocks_unaffordable_real_quote_without_execution():
    broker=NonBillingBroker(20)
    q=broker.quote('evaluation','owner','SELECT COUNT(*) AS n FROM shipments')
    assert q['price']>=35
    with patch('demo_economics.read_query') as execute:
        with pytest.raises(Conflict):broker.execute(q['id'],'owner')
        execute.assert_not_called()
    assert broker.executions==0

def test_nonbilling_success_is_real_sql_with_zero_query_charge():
    broker=NonBillingBroker(140)
    with patch('paypal_client.PayPalClient._request',side_effect=AssertionError('PayPal must never be called')):
        q=broker.quote('evaluation','owner','SELECT COUNT(*) AS shipment_count FROM shipments')
        result=broker.execute(q['id'],'owner')
    assert result['rows']==[{'shipment_count':600}]
    assert result['charged_cents']==0 and result['evaluation_price_cents']==q['price']

def test_recorded_output_does_not_claim_new_live_inference_or_optimization(capsys):
    report={'started_at_utc':'recorded','fresh_quotes':[{'sql_hash':'same','price':70,'plan':{'Total Cost':64}},{'sql_hash':'same','price':70,'plan':{'Total Cost':64}}],'available_evaluation_cents':50,'research':{'attempts':[],'message':'Refused'},'agent_sql_executions':0,'fresh_successful_query':{'rows':[{'shipment_count':600}]}}
    render_report(report)
    text=capsys.readouterr().out
    assert 'NOT a live model call' in text and 'not a successful optimization' in text

def test_economic_report_path_refuses_overwrite_before_provider_or_database_access(tmp_path,monkeypatch):
    existing=tmp_path/'historical.json';existing.write_text('{"preserve":true}',encoding='utf-8')
    monkeypatch.setenv('GROQ_API_KEY','mock-only')
    monkeypatch.setattr(sys,'argv',['demo_economics.py','--report-file',str(existing)])
    with patch('demo_economics.research') as model, patch('demo_economics.read_query') as query:
        with pytest.raises(SystemExit,match='Refusing to overwrite'):
            main()
        model.assert_not_called();query.assert_not_called()
    assert existing.read_text(encoding='utf-8')=='{"preserve":true}'
