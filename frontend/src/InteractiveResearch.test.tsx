import React from 'react';
import {expect,test} from 'vitest';
import {renderToStaticMarkup} from 'react-dom/server';
import InteractiveResearch,{formatResultValue,InteractiveDecision,mergeExecutionResult,Proposal,ResultTable,WorkflowStages} from './InteractiveResearch';
import {InteractiveStatus,interactiveStatusTitle} from './InteractiveStatus';

const proposalFixture:Proposal={
 plan_id:'fixture-plan',
 state:'quote_ready',
 objective:'Count synthetic shipments in October 2026.',
 message:'The proposal preserves the complete date range.',
 explanation:'Count every shipment in the requested month.',
 firewall:'passed',
 quote:{price_cents:35,expires_at:'2026-11-10T12:30:00Z',sql_hash:'fixture-sql-hash',accepted_ceiling_cents:35,available_cents:300,budget_decision:'affordable'},
 technical:{sql:'SELECT COUNT(*) AS shipment_count FROM vault_data.shipments',plan:{'Node Type':'Aggregate','Plan Rows':1}},
};
const renderDecision=(proposal:Proposal,accepted=false,busy='')=>renderToStaticMarkup(
 <InteractiveDecision proposal={proposal} accepted={accepted} busy={busy} focusTarget={null} onFocusHandled={()=>{}} onAcceptedChange={()=>{}} onAccept={()=>{}} onExecute={()=>{}}/>
);

test('interactive first screen makes the question the primary task without asserting a proposal',()=>{
 const html=renderToStaticMarkup(<InteractiveResearch/>);
 expect(html).toContain('Start with a question');
 expect(html).toContain('Your research question');
 expect(html).toContain('Generate proposal and quote');
 expect(html).toContain('Explore without AI');
 expect(html).toContain('placeholder="Write a logistics question, or choose an example below."');
 expect(html).not.toContain('Which port had the highest average shipment delay');
 expect(html).not.toContain('Proposal and decision');
 expect(html).toContain('aria-label="Research decision stages"');
 expect(html).toContain('Current stage · Question');
 expect(html).toContain('Examples fill the editor; they never submit it.');
 expect(html).toContain('role="progressbar"');
});

test('workflow strip advances from question through decision to result and marks refusals honestly',()=>{
 const quote=renderToStaticMarkup(<WorkflowStages state="quote_ready" hasQuote hasFirewall/>);
 expect(quote).toContain('Current stage · Acceptance');
 expect(quote).toContain('aria-current="step"');
 const completed=renderToStaticMarkup(<WorkflowStages state="completed" hasQuote hasFirewall/>);
 expect(completed).toContain('Current stage · Result');
 const refused=renderToStaticMarkup(<WorkflowStages state="over_budget" hasQuote hasFirewall/>);
 expect(refused).toContain('Stopped at quote · no later stage ran.');
});

test('interactive state names explain checking, planning, quote, refusal and completion',()=>{
 expect(interactiveStatusTitle('checking')).toContain('Checking');
 expect(interactiveStatusTitle('planning')).toBe('AI planning');
 expect(interactiveStatusTitle('quote_ready')).toContain('awaiting demo acceptance');
 expect(interactiveStatusTitle('over_budget')).toContain('allowance');
 expect(interactiveStatusTitle('scope_review')).toContain('Scope review');
 expect(interactiveStatusTitle('refused')).toContain('refused');
 expect(interactiveStatusTitle('completed')).toBe('Research completed');
});

test('loading and provider failure use accessible status and alert roles',()=>{
 const loading=renderToStaticMarkup(<InteractiveStatus state="planning" busy="Planning research"/>);
 expect(loading).toContain('role="status"');expect(loading).toContain('aria-live="polite"');expect(loading).toContain('AI planning');
 const error=renderToStaticMarkup(<InteractiveStatus state="provider_unavailable" error="The research provider is unavailable."/>);
 expect(error).toContain('role="alert"');expect(error).toContain('Provider unavailable');
});

test('fixture proposal connects firewall, quote, allowance, acceptance and proposed SQL disclosure',()=>{
 const html=renderDecision(proposalFixture);
 expect(html).toContain('Research question');
 expect(html).toContain('AI proposal received');
 expect(html).toContain('SQL firewall · passed');
 expect(html).toContain('$0.35 quoted · $3.00 virtual allowance available');
 expect(html).toContain('I accept this quoted amount from my virtual, non-billing demo allowance');
 expect(html).toContain('Inspect proposed SQL and PostgreSQL plan · not executed yet');
 expect(html).toContain('not executed yet');
});

test('accepted fixture presents execution as the one next action',()=>{
 const html=renderDecision({...proposalFixture,state:'accepted',message:'$0.35 reserved from the virtual allowance.'});
 expect(html).toContain('Virtual budget decision · accepted');
 expect(html).toContain('Execute accepted read-only query');
 expect(html).not.toContain('Accept demo quote');
 expect(html).not.toContain('Actual read-only result');
});

test('executing fixture does not claim a result or charge',()=>{
 const html=renderToStaticMarkup(<><InteractiveStatus state="executing" busy="Executing query"/><InteractiveDecision proposal={{...proposalFixture,state:'executing'}} accepted={false} busy="Executing query" focusTarget={null} onFocusHandled={()=>{}} onAcceptedChange={()=>{}} onAccept={()=>{}} onExecute={()=>{}}/></>);
 expect(html).toContain('Executing the validated read-only query');
 expect(html).toContain('Database execution · in progress');
 expect(html).not.toContain('Actual read-only result');
 expect(html).not.toContain('Virtual allowance used');
});

test('completed fixture distinguishes executed SQL from the exact saved result values',()=>{
 const completed:Proposal={...proposalFixture,state:'completed',message:'The read-only query returned one row.',result:{rows:[{shipment_count:600,average_delay:'21.0933333333333333'}],charged_cents:35,label:'Virtual demo allowance — no real payment'}};
 const html=renderDecision(completed);
 expect(html).toContain('Database execution · completed');
 expect(html).toContain('Inspect executed SQL and pre-execution PostgreSQL plan');
 expect(html).toContain('Actual read-only result');
 expect(html).toContain('21.09');
 expect(html).toContain('21.0933333333333333');
 expect(html).toContain('Inspect exact database values');
 expect(html).toContain('no real payment');
 expect(html).not.toContain('PayPal authorization');
});

test('execution response retains the accepted SQL and quote for completed evidence',()=>{
 const response:Partial<Proposal>={state:'completed',message:'The accepted query completed.',
  result:{rows:[{shipment_count:600}],charged_cents:35,label:'Virtual demo allowance — no real payment'}};
 const completed=mergeExecutionResult(proposalFixture,response);
 const html=renderDecision(completed);
 expect(completed.quote?.sql_hash).toBe(proposalFixture.quote?.sql_hash);
 expect(completed.technical?.sql).toBe(proposalFixture.technical?.sql);
 expect(html).toContain('Inspect executed SQL and pre-execution PostgreSQL plan');
 expect(html).toContain('This is the SQL bound to the accepted quote');
 expect(html).toContain('SELECT COUNT(*) AS shipment_count FROM vault_data.shipments');
 expect(html).toContain('SQL SHA-256 · fixture-sql-hash');
 expect(html).toContain('Actual read-only result');
});

test('execution-time firewall pass is not rendered as a rejection',()=>{
 const completed:Proposal={...proposalFixture,state:'completed',firewall:'passed again immediately before execution',message:'The accepted query completed.',result:{rows:[{shipment_count:600}],charged_cents:35,label:'Virtual demo allowance — no real payment'}};
 const html=renderDecision(completed);
 expect(html).toContain('SQL firewall · passed again immediately before execution');
 expect(html).toContain('The SQL was parsed, scoped to the synthetic schema and approved for read-only planning.');
 expect(html).not.toContain('The proposal was rejected. No price or result was produced from it.');
});

test('unaffordable quote is a refusal with no acceptance, execution, or result',()=>{
 const refused:Proposal={...proposalFixture,state:'over_budget',message:'The $0.70 quote exceeds the $0.50 available allowance.',quote:{...proposalFixture.quote!,price_cents:70,accepted_ceiling_cents:70,available_cents:50,budget_decision:'over_budget'},technical:null};
 const html=renderDecision(refused);
 expect(html).toContain('STOPPED · OVER BUDGET');
 expect(html).toContain('$0.70 quoted · $0.50 virtual allowance available');
 expect(html).toContain('Budget decision · refused');
 expect(html).toContain('not forced to narrow the scope');
 expect(html).toContain('No query was executed');
 expect(html).not.toContain('Accept demo quote');
 expect(html).not.toContain('Execute accepted read-only query');
 expect(html).not.toContain('Actual read-only result');
});

for(const [state,title] of [['scope_review','stopped for scope review'],['sql_rejected','SQL firewall rejected the proposal'],['refused','AI proposal · refused'],['provider_unavailable','AI planning · unavailable']] as const){
 test(state+' fixture stops without a quote or execution',()=>{
  const html=renderDecision({...proposalFixture,state,message:'Fixture outcome: '+state+'. No execution occurred.',firewall:state==='sql_rejected'?'rejected':undefined,quote:null,technical:null});
  expect(html).toContain(title);
  expect(html).toContain('No result is available');
  expect(html).not.toContain('Deterministic quote');
  expect(html).not.toContain('Execute accepted read-only query');
  expect(html).not.toContain('Actual read-only result');
 });
}

test('result values are formatted for scanning while retaining exact values',()=>{
 expect(formatResultValue('21.0933333333333333')).toEqual({display:'21.09',exact:'21.0933333333333333',numeric:true});
 expect(formatResultValue(600)).toEqual({display:'600',exact:'600',numeric:true});
 expect(formatResultValue('Chennai')).toEqual({display:'Chennai',exact:'Chennai',numeric:false});
 const html=renderToStaticMarkup(<ResultTable result={{rows:[{count:600,delay:'21.0933333333333333'}],charged_cents:0,label:'Free synthetic preview'}}/>);
 expect(html).toContain('aria-label="21.09; exact value 21.0933333333333333"');
 expect(html).toContain('Inspect exact database values');
});
