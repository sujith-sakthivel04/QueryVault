import {money} from './api';
type Decision={attempt?:number;reason?:string;price_cents?:number;remaining_cents?:number;sql?:string;quote_id?:string};
type RecordData={decisions?:Decision[];result?:{rows?:unknown[];charged_cents?:number};requires_approval?:boolean;refused?:boolean;message?:string;mode?:string};

export default function DecisionTimeline({record,historical=false,error}:{record?:RecordData;historical?:boolean;error?:string}){
 const decisions=record?.decisions||[];
 return <section className="decision-record" aria-label={historical?'Historical agent decision timeline':'Agent decision timeline'}>
  <div className="decision-title"><h3>How the agent chose</h3><span className="badge">{historical?'SAVED RECORD · NOT LIVE':'CURRENT REQUEST'}</span></div>
  {historical&&<p className="fine">Previously recorded decisions. No live model request or query is triggered by viewing this timeline.</p>}
  <ol className="decision-timeline">
   {decisions.map((d,i)=><li key={d.quote_id||i}>
    <h4>{decisions.length>1?`Proposal ${d.attempt||i+1}: `:''}Choose a query that preserves the brief</h4><p>{d.reason||'A SQL proposal was recorded for this research objective.'}</p>
    {typeof d.price_cents==='number'&&<div className="decision-budget"><strong>Quoted {money(d.price_cents)}</strong>{typeof d.remaining_cents==='number'&&<span> · {money(d.remaining_cents)} available at the decision</span>}<p>{typeof d.remaining_cents==='number'?(d.price_cents<=d.remaining_cents?'Within the available query budget.':'Above the available query budget; this proposal was not executed.'):'The fixed quote is recorded; this entry does not include a remaining-budget snapshot.'}</p></div>}
    <details><summary>SQL & quote details</summary>{d.sql&&<pre>{d.sql}</pre>}<pre>{JSON.stringify({attempt:d.attempt,quote_id:d.quote_id,quoted_cents:d.price_cents,remaining_budget_cents:d.remaining_cents},null,2)}</pre></details>
   </li>)}
   {record?.result&&<li><h4>Result recorded</h4><p>{record.result.rows?.length??0} rows returned{typeof record.result.charged_cents==='number'?`; recorded query charge ${money(record.result.charged_cents)}.`:'.'} Payment settlement is shown separately.</p></li>}
   {record?.requires_approval&&<li><h4>Stopped for human review</h4><p>{record.message||'A changed scope requires approval before execution.'}</p></li>}
   {record?.refused&&<li><h4>Stopped without execution</h4><p>{record.message||'No affordable validated same-scope query was found within the attempt limit.'}</p></li>}
   {error&&<li><h4>Request did not complete</h4><p>{error}</p></li>}
  </ol>
  {!decisions.length&&!record?.requires_approval&&!record?.refused&&!error&&<p>{record?.message||'No decision record is available for this request.'}</p>}
  {!!decisions.length&&!record?.result&&!record?.requires_approval&&!error&&<p className="fine">A proposal and quote do not establish that a query executed or a payment completed.</p>}
 </section>
}
