"""Real non-billing economic decision demo using the existing research loop.

The adapter uses real SQL validation, EXPLAIN and the production price table.
Its cents are an evaluation allowance, NOT a PayPal authorization or ledger.
No financial session, payment factory or mutable database connection is used.
"""
import argparse
from datetime import datetime,timezone,timedelta
import hashlib
import json
import sys
import os
from pathlib import Path
from uuid import uuid4
from agent import research
from db import read_query
from engine import price_plan,Conflict
from firewall import QueryFirewall,POLICY_VERSION

OBJECTIVE=('For every port with shipments during the entire month October 2026, return port_name and avg_delay_hours, '
           'round average delay to two decimal places, and order by port_name ascending. Preserve the full month and port-level granularity.')
REFERENCE="SELECT p.name AS port_name, ROUND(AVG(s.delay_hours),2) AS avg_delay_hours FROM shipments s JOIN ports p ON s.port_id=p.id WHERE s.shipped_on BETWEEN '2026-10-01' AND '2026-10-31' GROUP BY p.name ORDER BY p.name"

class NonBillingBroker:
    def __init__(self,budget_cents):
        if type(budget_cents) is not int or budget_cents<0:raise ValueError('Evaluation allowance must be nonnegative integer cents')
        self.budget=budget_cents;self.used=0;self.quotes={};self.events=[];self.executions=0

    def get(self,sid,owner):return {'budget':self.budget,'spent':self.used,'reserved':0}

    def quote(self,sid,owner,sql):
        approved=QueryFirewall().validate(sql)
        plan=read_query(approved,explain=True)
        q={'id':str(uuid4()),'sql':approved,'sql_hash':hashlib.sha256(approved.encode()).hexdigest(),'price':price_plan(plan),'policy':POLICY_VERSION,'expires_at':datetime.now(timezone.utc)+timedelta(minutes=5),'plan':{k:plan[k] for k in ('Node Type','Total Cost','Plan Rows')}}
        self.quotes[q['id']]=q
        self.events.append({'event':'fresh_nonbilling_quote',**q})
        print(f"Fresh quote {len(self.quotes)}: {q['price']} cents; available evaluation allowance {self.budget-self.used} cents; planner cost {plan['Total Cost']}",flush=True)
        return q

    def execute(self,qid,owner):
        q=self.quotes[qid]
        if q['expires_at']<=datetime.now(timezone.utc) or q['price']>self.budget-self.used:
            raise Conflict('Expired or unaffordable evaluation quote; no SQL executed')
        rows=json.loads(json.dumps(read_query(q['sql']),default=str))
        self.used+=q['price'];self.executions+=1
        return {'rows':rows,'charged_cents':0,'evaluation_price_cents':q['price'],'quote_id':qid,'mode':'real read-only execution; no financial charge'}

def render_report(report,live=False):
    print('LIVE RUN RESULTS' if live else 'RECORDED real non-billing evaluation - NOT a live model call')
    print('Run started:',report['started_at_utc'])
    quotes=report['fresh_quotes'];unique=len({q['sql_hash'] for q in quotes})
    for i,q in enumerate(quotes,1):
        print(f"Quote {i}: {q['price']} cents vs {report['available_evaluation_cents']} available; PostgreSQL cost {q['plan']['Total Cost']}")
    for a in report['research'].get('attempts',[]):
        print(f"Proposal {a['attempt']}: {a['outcome']}")
    print(f'Observed normalized plans: {unique}; fresh quotes: {len(quotes)}')
    if len(quotes)>1 and unique==1:print('The requote is the SAME plan, not a successful optimization. No price reduction was observed.')
    print('Decision:',report['research'].get('message') or 'Executed within the evaluation allowance.')
    print('Agent SQL executions:',report['agent_sql_executions'])
    if report.get('semantic_result_matches_reference') is not None:
        print('Independent reference result match:',report['semantic_result_matches_reference'])
    print('Separate successful read-only verification during this run:',report['fresh_successful_query']['rows'])
    print('No PayPal calls, financial sessions or query fees. Groq provider usage still applies to live runs.')

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--budget-cents',type=int,default=50)
    parser.add_argument('--report-file',type=Path,help='new local report path; existing files are never replaced')
    args=parser.parse_args()
    if not os.getenv('GROQ_API_KEY'):
        raise SystemExit('A live evaluation requires the operator to configure their own GROQ_API_KEY; no inference was performed.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    report_path=args.report_file or Path('.local')/'evaluations'/f'economic-demo-{stamp}.json'
    if report_path.exists():
        raise SystemExit('Refusing to overwrite an existing economic evaluation report.')
    report_path.parent.mkdir(parents=True,exist_ok=True)
    broker=NonBillingBroker(args.budget_cents)
    started=datetime.now(timezone.utc).isoformat()
    print('LIVE Groq + real PostgreSQL. NON-BILLING EVALUATION. No PayPal session or payment.',flush=True)
    print('Frozen objective:',OBJECTIVE,flush=True)
    result=research(broker,'nonbilling-evaluation','evaluation-only',OBJECTIVE)
    expected=json.loads(json.dumps(read_query(REFERENCE),default=str))
    # Always perform one separate useful fresh query, not a paid-session bypass.
    fresh_sql=QueryFirewall().validate("SELECT COUNT(*) AS shipment_count FROM shipments WHERE shipped_on BETWEEN '2026-10-01' AND '2026-10-31'")
    fresh_rows=read_query(fresh_sql)
    assert fresh_rows==[{'shipment_count':600}]
    report={'mode':'real non-billing Groq economic decision evaluation','started_at_utc':started,'available_evaluation_cents':args.budget_cents,'production_minimum_quote_cents':price_plan({'Total Cost':0}),'objective':OBJECTIVE,'research':result,'fresh_quotes':broker.events,'billable_session_created':False,'paypal_calls':0,'query_fees_charged_cents':0,'agent_sql_executions':broker.executions,'semantic_result_matches_reference':result.get('result',{}).get('rows')==expected if result.get('result') else None,'independent_reference_rows':expected,'fresh_successful_query':{'sql':fresh_sql,'rows':fresh_rows,'mode':'separate free read-only verification; not an agent purchase or optimized plan'}}
    report_path.write_text(json.dumps(report,default=str,indent=2))
    print(f'Evaluation report saved locally to {report_path.as_posix()}')
    render_report(report,live=True)

if __name__=='__main__':main()
