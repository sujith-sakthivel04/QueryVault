import React,{useCallback,useEffect,useRef,useState} from 'react';
import {api,money} from './api';
import {InteractiveStatus,interactiveStatusTitle} from './InteractiveStatus';
import ProofEngine,{ProofEvidence} from './ProofEngine';

export type Wallet={enabled:boolean;label:string;allowance_cents:number;spent_cents:number;reserved_cents:number;available_cents:number;daily_ai_calls_used:number;daily_ai_calls_limit:number;daily_ai_tokens_reserved:number;daily_ai_tokens_limit:number;lifetime_ai_calls_used:number;lifetime_ai_calls_limit:number;lifetime_ai_tokens_reserved:number;lifetime_ai_tokens_limit:number;visitor_ai_calls_used:number;visitor_ai_calls_limit:number;daily_queries_used:number;daily_queries_limit:number;visitor_queries_used:number;visitor_queries_limit:number};
export type Proposal={plan_id:string;state:string;objective:string;message:string;explanation?:string;firewall?:string;model_tokens_used?:number|null;quote?:{price_cents:number;expires_at:string;sql_hash:string;accepted_ceiling_cents:number;available_cents:number;budget_decision:string}|null;technical?:{sql:string;plan:Record<string,unknown>}|null;result?:{rows:Record<string,unknown>[];charged_cents:number;label:string};allowance?:Wallet};
type Result={rows:Record<string,unknown>[];charged_cents:number;label:string};
type FocusTarget='proposal'|'execute'|'result'|null;

export function mergeExecutionResult(proposal:Proposal,result:Partial<Proposal>):Proposal{
 return {...proposal,...result,quote:proposal.quote,technical:proposal.technical};
}

function firewallOutcome(status?:string):'passed'|'rejected'|'not_run'{
 const normalized=status?.trim().toLowerCase()||'';
 if(normalized==='rejected'||normalized.startsWith('rejected '))return 'rejected';
 if(normalized==='passed'||normalized.startsWith('passed '))return 'passed';
 return 'not_run';
}

const examples=['Which port had the highest average shipment delay in October 2026?','How many shipments occurred in October 2026?','What is the average container count by port?','Which routes experienced the longest delays?','Compare average delays across every shipment route in October 2026.'];
function workflowPosition(state:string,hasQuote:boolean,hasFirewall:boolean){
 if(state==='completed')return 6;
 if(state==='accepted'||state==='executing')return 5;
 if(state==='quote_ready')return 4;
 if(state==='over_budget')return 3;
 if(['stale_quote','invalid_acceptance'].includes(state))return 4;
 if(['sql_rejected','scope_review'].includes(state))return 2;
 if(['provider_unavailable','failed','error','refused'].includes(state))return 1;
 if(hasQuote)return 3;
 if(hasFirewall)return 2;
 if(state==='planning'||state==='ready'||state==='checking')return state==='planning'?1:0;
 return 1;
}

export function WorkflowStages({state,hasQuote,hasFirewall,proposal,question}:{state:string;hasQuote:boolean;hasFirewall:boolean;proposal?:Proposal;question?:string}){
 const current=workflowPosition(state,hasQuote,hasFirewall);
 const stopped=['over_budget','scope_review','sql_rejected','refused','provider_unavailable','failed','error','stale_quote','invalid_acceptance'].includes(state);
 const evidence:ProofEvidence={};
 const objective=proposal?.objective||question;
 if(objective)evidence.Question=<p className="proof-copy">{objective}</p>;
 if(proposal)evidence.Proposal=<div className="proof-stack"><strong>{proposal.state.replaceAll('_',' ')}</strong><p>{proposal.explanation||proposal.message}</p></div>;
 if(proposal?.firewall){const outcome=firewallOutcome(proposal.firewall);evidence.Validation=<div className="proof-stack"><strong>SQL firewall · {proposal.firewall}</strong><p>{outcome==='passed'?'The validated SQL cleared the read-only policy checks.':outcome==='rejected'?'The proposal was rejected and no execution followed.':'The SQL firewall was not run; the proposal was not quoted or executed.'}</p></div>}
 if(proposal?.technical&&!proposal.firewall)evidence.Validation=<div className="proof-stack"><strong>Validated query plan</strong><p>PostgreSQL returned a plan for the read-only proposal.</p></div>;
 if(proposal?.quote)evidence.Quote=<div className="proof-stack proof-numbers"><strong>{money(proposal.quote.price_cents)}</strong><p>{proposal.quote.budget_decision==='affordable'?'Within the displayed virtual allowance.':'Above the available virtual allowance; execution did not proceed.'}</p><span>SQL fingerprint · {proposal.quote.sql_hash}</span></div>;
 if(proposal&&['accepted','executing','completed'].includes(proposal.state))evidence.Acceptance=<div className="proof-stack"><strong>Explicit demo acceptance recorded</strong><p>{proposal.message}</p></div>;
 if(proposal&&['executing','completed'].includes(proposal.state))evidence.Execution=<div className="proof-stack"><strong>{proposal.state==='completed'?'Read-only execution completed':'Read-only execution in progress'}</strong><p>No PayPal payment or commercial session is part of this public mode.</p></div>;
 if(proposal?.result)evidence.Result=<div className="proof-stack"><strong>{proposal.result.rows.length} rows returned</strong><p>{proposal.result.label} · {money(proposal.result.charged_cents)} of virtual allowance used</p></div>;
 return <ProofEngine activeStage={current} state={interactiveStatusTitle(state)} evidence={evidence} stopped={stopped} complete={state==='completed'}/>;
}

export default function InteractiveResearch(){
 const [wallet,setWallet]=useState<Wallet>();const [question,setQuestion]=useState('');const [proposal,setProposal]=useState<Proposal>();const [error,setError]=useState('');const [busy,setBusy]=useState('');const [accepted,setAccepted]=useState(false);const [preview,setPreview]=useState<any>();const [focusTarget,setFocusTarget]=useState<FocusTarget>(null);
 const markFocusHandled=useCallback(()=>setFocusTarget(null),[]);
 async function refresh(){const next=await api('/interactive/state');setWallet(next)}
 useEffect(()=>{void (async()=>{await refresh();const saved=sessionStorage.getItem('qv.interactive.plan');if(saved){try{setProposal(await api('/interactive/plans/'+encodeURIComponent(saved)))}catch(e){setError((e as Error).message)}}})().catch(e=>setError((e as Error).message))},[]);
 async function run(label:string,fn:()=>Promise<void>){setBusy(label);setError('');try{await fn()}catch(e){const failure=e as Error&{code?:string};const state=failure.code==='provider_unavailable'?'provider_unavailable':'error';setError(failure.message);setProposal(p=>p?{...p,state,message:failure.message}:{plan_id:'',state,objective:question,message:failure.message})}finally{setBusy('')}}
 async function plan(){setProposal(undefined);setPreview(undefined);setAccepted(false);sessionStorage.removeItem('qv.interactive.plan');const p=await api('/interactive/plan',{objective:question,request_id:crypto.randomUUID()});sessionStorage.setItem('qv.interactive.plan',p.plan_id);setFocusTarget('proposal');setProposal(p);await refresh()}
 async function accept(){if(!proposal?.quote)return;await api('/interactive/accept',{plan_id:proposal.plan_id,sql_hash:proposal.quote.sql_hash,accepted_price_cents:proposal.quote.accepted_ceiling_cents});setFocusTarget('execute');setProposal(p=>p?{...p,state:'accepted',message:'The quoted amount is now reserved inside the non-billing demo allowance. No payment occurred.'}:p);setAccepted(false);await refresh()}
 async function execute(){if(!proposal)return;setProposal(p=>p?{...p,state:'executing'}:p);const result=await api('/interactive/execute',{plan_id:proposal.plan_id});setFocusTarget('result');setProposal(mergeExecutionResult(proposal,result));await refresh()}
 async function previewQuery(template:'port_delays'|'shipment_count'){const result=await api('/demo/query',{template});setPreview(result);setProposal(undefined);sessionStorage.removeItem('qv.interactive.plan');await refresh()}
 const state=busy==='Planning research'?'planning':busy==='Executing query'?'executing':proposal?.state||(!wallet?'checking':'ready');
 const available=wallet?.available_cents??0;
 const allowance=wallet?.allowance_cents??0;
 const used=wallet?Math.max(0,wallet.spent_cents+wallet.reserved_cents):0;
 const consumedPercent=allowance>0?Math.min(100,Math.round(used/allowance*100)):0;
 return <div className="interactive-workspace">
  <section className="panel interactive-panel interactive-primary" aria-labelledby="interactive-question-title">
   <div className="panelhead"><div><h2 id="interactive-question-title">Start with a question</h2></div><span className="badge">{wallet?(wallet.enabled?'AI AVAILABLE':'AI DISABLED'):'CHECKING AVAILABILITY'}</span></div>
   <p className="muted">A proposal is validated and quoted before any accepted query runs against the synthetic October 2026 dataset.</p>
   <label htmlFor="interactive-question">Your research question</label>
   <p className="field-hint" id="interactive-question-help">Ask about shipments, ports, or routes. Examples fill the editor; they never submit it.</p>
   <textarea id="interactive-question" aria-describedby="interactive-question-help" placeholder="Write a logistics question, or choose an example below." disabled={!!busy||wallet?.enabled===false} maxLength={500} value={question} onChange={e=>setQuestion(e.target.value)}/>
   <div className="interactive-submit-row">
    <button disabled={!!busy||wallet?.enabled!==true||question.trim().length<8} onClick={()=>void run('Planning research',plan)}>{busy==='Planning research'?'Planning…':'Generate proposal and quote'}</button>
    <div className="allowance-compact" aria-label={'Virtual demo allowance: '+money(available)+' available'}>
     <div className="allowance-label-row"><strong>Virtual allowance</strong><strong>{money(available)} left</strong></div>
     <div className="allowance-meter" role="progressbar" aria-label="Virtual allowance reserved or spent" aria-valuemin={0} aria-valuemax={allowance} aria-valuenow={used} aria-valuetext={`${money(used)} of ${money(allowance)} reserved or spent`}><span style={{width:consumedPercent+'%'}}/></div>
     <span>{money(wallet?.spent_cents??0)} spent · {money(wallet?.reserved_cents??0)} reserved · {proposal?.quote?money(proposal.quote.price_cents)+' quoted':''}</span>
     <span>Non-billing demo balance; separate from historical PayPal evidence.</span>
    </div>
   </div>
   {wallet?.enabled===false&&<AiDisabledNotice/>}
   {wallet?.enabled===true&&<div className="interactive-examples"><span>Supported examples</span>{examples.slice(0,4).map(example=><button className="example-button" key={example} disabled={!!busy} onClick={()=>setQuestion(example)}>{example}</button>)}</div>}
   <InteractiveStatus state={state} busy={busy} error={error}/>
   <WorkflowStages state={state} hasQuote={!!proposal?.quote} hasFirewall={!!proposal?.firewall} proposal={proposal} question={question}/>
   {proposal&&<InteractiveDecision proposal={proposal} accepted={accepted} busy={busy} focusTarget={focusTarget} onFocusHandled={markFocusHandled} onAcceptedChange={setAccepted} onAccept={()=>void run('Accepting demo quote',accept)} onExecute={()=>void run('Executing query',execute)}/>}
  </section>
  <section className="panel interactive-panel interactive-fallback" id="interactive-fallback" aria-labelledby="interactive-fallback-title">
   <div className="panelhead"><span className="number">02</span><h2 id="interactive-fallback-title">Explore without AI</h2><span className="badge">NO INFERENCE · NO PAYMENT</span></div>
   <p className="muted">These fixed examples run against the read-only synthetic database. Results are actual database responses, not scripted answers.</p>
   <div className="actions"><button disabled={!!busy} onClick={()=>void run('Running fixed query',()=>previewQuery('port_delays'))}>Average delays by port</button><button className="secondary" disabled={!!busy} onClick={()=>void run('Running fixed query',()=>previewQuery('shipment_count'))}>Count synthetic shipments</button></div>
   {preview&&<ResultTable result={{rows:preview.rows,charged_cents:0,label:'Free synthetic preview — no AI call or payment'}}/>}
   <div className="demo-allowance quota-summary"><span>AI calls today {wallet?.daily_ai_calls_used??0} / {wallet?.daily_ai_calls_limit??0}</span><span>Lifetime AI calls {wallet?.lifetime_ai_calls_used??0} / {wallet?.lifetime_ai_calls_limit??0}</span><span>Reserved provider tokens {wallet?.daily_ai_tokens_reserved??0} / {wallet?.daily_ai_tokens_limit??0} today · {wallet?.lifetime_ai_tokens_reserved??0} / {wallet?.lifetime_ai_tokens_limit??0} overall</span><span>Your AI calls today {wallet?.visitor_ai_calls_used??0} / {wallet?.visitor_ai_calls_limit??0}</span><span>Read-only runs today {wallet?.daily_queries_used??0} / {wallet?.daily_queries_limit??0}</span></div>
  </section>
 </div>
}

export function AiDisabledNotice(){
 return <div className="alert ai-disabled-note" role="status">Public AI is disabled by the operator. Choose a fixed read-only example below; it uses no inference or payment. <a href="#interactive-fallback">Go to the free examples</a></div>;
}

export function InteractiveDecision({proposal,accepted,busy,focusTarget,onFocusHandled,onAcceptedChange,onAccept,onExecute}:{proposal:Proposal;accepted:boolean;busy:string;focusTarget:FocusTarget;onFocusHandled:()=>void;onAcceptedChange:(value:boolean)=>void;onAccept:()=>void;onExecute:()=>void}){
 const proposalRef=useRef<HTMLElement>(null);const executeRef=useRef<HTMLButtonElement>(null);const resultHeadingRef=useRef<HTMLHeadingElement>(null);
 const firewall=firewallOutcome(proposal.firewall);
 useEffect(()=>{
  if(focusTarget==='proposal'){proposalRef.current?.focus();onFocusHandled()}
  else if(focusTarget==='execute'&&proposal.state==='accepted'&&!busy){executeRef.current?.focus();onFocusHandled()}
  else if(focusTarget==='result'&&proposal.state==='completed'&&!busy){resultHeadingRef.current?.focus();onFocusHandled()}
 },[proposal.state,busy,focusTarget,onFocusHandled]);
 const stopState=['scope_review','sql_rejected','refused','provider_unavailable','failed','stale_quote','error'].includes(proposal.state);
 const proposalTitle=proposal.state==='provider_unavailable'?'AI planning · unavailable':proposal.state==='error'||proposal.state==='failed'?'Research request · failed':proposal.state==='scope_review'?'AI proposal · stopped for scope review':proposal.state==='sql_rejected'?'AI proposal · rejected by firewall':proposal.state==='refused'?'AI proposal · refused':'AI proposal received';
 const expires=proposal.quote?new Date(proposal.quote.expires_at):undefined;
 return <section className="proposal-record" ref={proposalRef} tabIndex={-1} aria-labelledby="interactive-decision-title">
  <div className="decision-title"><h3 id="interactive-decision-title">Proposal and decision</h3><span className="badge">{proposal.state==='completed'?'COMPLETED':proposal.state==='over_budget'?'STOPPED · OVER BUDGET':proposal.state.replaceAll('_',' ').toUpperCase()}</span></div>
  <ol className="decision-timeline" aria-label="Research decision steps">
   <li><h4>Research question</h4><p>{proposal.objective}</p><details><summary>Technical request details</summary><pre>{JSON.stringify({plan_id:proposal.plan_id||undefined},null,2)}</pre></details></li>
   <li><h4>{proposalTitle}</h4><p>{proposal.explanation||proposal.message}</p>{firewall==='passed'&&proposal.state!=='completed'&&<p className="fine">The planner says this SQL preserves the question. The firewall checks SQL safety, not natural-language equivalence; inspect the proposal before accepting.</p>}</li>
   {proposal.firewall&&<li><h4>SQL firewall · {proposal.firewall}</h4><p>{firewall==='passed'?'The SQL was parsed, scoped to the synthetic schema and approved for read-only planning.':firewall==='rejected'?'The proposal was rejected. No price or result was produced from it.':'The SQL firewall was not run; no quote or result was produced.'}</p></li>}
   {proposal.quote&&<li><h4>Deterministic quote · {money(proposal.quote.price_cents)}</h4><div className={'decision-budget '+(proposal.quote.budget_decision==='affordable'?'':'over-budget')}><strong>{money(proposal.quote.price_cents)} quoted · {money(proposal.quote.available_cents)} virtual allowance available</strong><p>{proposal.quote.budget_decision==='affordable'?'The full-scope plan fits the virtual allowance.':'The full-scope plan exceeds the allowance; no query was accepted or executed.'}</p><p>Accepted ceiling {money(proposal.quote.accepted_ceiling_cents)} · expires {expires&&!Number.isNaN(expires.valueOf())?expires.toLocaleTimeString():'not available'}</p></div>{proposal.quote.budget_decision==='affordable'&&proposal.state==='quote_ready'&&<div className="accept-demo"><label><input type="checkbox" checked={accepted} onChange={e=>onAcceptedChange(e.target.checked)}/> I accept this quoted amount from my virtual, non-billing demo allowance.</label><button disabled={!accepted||!!busy} onClick={onAccept}>Accept demo quote · {money(proposal.quote.price_cents)}</button></div>}</li>}
   {proposal.state==='accepted'&&<li><h4>Virtual budget decision · accepted</h4><p>{proposal.message}</p><button ref={executeRef} disabled={!!busy} onClick={onExecute}>Execute accepted read-only query</button></li>}
   {proposal.state==='executing'&&<li><h4>Database execution · in progress</h4><p>The validated, accepted query is running against the read-only synthetic database. No payment is being made.</p></li>}
   {proposal.state==='completed'&&<li><h4>Database execution · completed</h4><p>{proposal.message} Virtual allowance used {money(proposal.result?.charged_cents||0)}. No PayPal or commercial session was created.</p></li>}
   {proposal.state==='over_budget'&&<li><h4>Budget decision · refused</h4><p>{proposal.message} The agent is not forced to narrow the scope or invent a cheaper plan. No query was executed.</p></li>}
   {stopState&&<li><h4>Stopped · {interactiveStatusTitle(proposal.state)}</h4><p>{proposal.message||'No query was executed.'} No result is available.</p></li>}
  </ol>
  {proposal.technical&&<details className="proposal-technical"><summary>{proposal.state==='completed'?'Inspect executed SQL and pre-execution PostgreSQL plan':'Inspect proposed SQL and PostgreSQL plan · not executed yet'}</summary><p className="fine">{proposal.state==='completed'?'This is the SQL bound to the accepted quote and revalidated immediately before execution.':'The validated SQL is proposed for a read-only query. Execution occurs only after virtual acceptance.'}</p><pre>{proposal.technical.sql}</pre><pre>{JSON.stringify(proposal.technical.plan,null,2)}</pre><pre>SQL SHA-256 · {proposal.quote?.sql_hash}</pre></details>}
  {proposal.result&&<ResultTable result={proposal.result} headingRef={node=>{resultHeadingRef.current=node}}/>}
 </section>
}

export function formatResultValue(value:unknown){
 const exact=String(value);
 const isDecimal=(typeof value==='number'&&Number.isFinite(value)&&!Number.isInteger(value))||(typeof value==='string'&&/^-?\d+\.\d+$/.test(value));
 if(!isDecimal)return {display:exact,exact,numeric:(typeof value==='number'&&Number.isFinite(value))||(typeof value==='string'&&/^-?\d+(?:\.\d+)?$/.test(value))};
 const number=Number(value);
 return {display:new Intl.NumberFormat(undefined,{maximumFractionDigits:2}).format(number),exact,numeric:true};
}

export function ResultTable({result,headingRef}:{result:Result;headingRef?:(node:HTMLHeadingElement|null)=>void}){
 const columns=Object.keys(result.rows?.[0]||{});
 return <section className="interactive-results" aria-label="Query result"><div className="results-heading"><h4 tabIndex={-1} ref={headingRef}>Actual read-only result</h4><span>{result.rows?.length||0} rows · {result.label}</span></div>{columns.length>0?<><div className="results\"><table><thead><tr>{columns.map(k=><th scope="col" key={k}>{k}</th>)}</tr></thead><tbody>{result.rows.map((row,i)=><tr key={i}>{columns.map(k=>{const value=formatResultValue(row[k]);return <td className={value.numeric?'numeric-cell':''} aria-label={value.exact!==value.display?value.display+'; exact value '+value.exact:undefined} title={value.exact!==value.display?'Exact value: '+value.exact:undefined} key={k}>{value.display}</td>})}</tr>)}</tbody></table></div><details className="exact-results"><summary>Inspect exact database values</summary><pre>{JSON.stringify(result.rows,null,2)}</pre></details></>:<p>No rows returned.</p>}</section>
}
