import React from 'react';

const titles:Record<string,string>={checking:'Checking research availability',ready:'Ready for a research question',planning:'AI planning',quote_ready:'Quote ready · awaiting demo acceptance',over_budget:'Over the available demo allowance',scope_review:'Scope review required',sql_rejected:'SQL firewall rejected the proposal',refused:'The planner refused this request',accepted:'Demo amount reserved · awaiting execution',executing:'Executing the validated read-only query',completed:'Research completed',provider_unavailable:'Provider unavailable',failed:'Request could not be completed',stale_quote:'Quote expired or changed',error:'Request needs attention'};
export const interactiveStatusTitle=(state:string)=>titles[state]||titles.error;

export function InteractiveStatus({state,busy,error}:{state:string;busy?:string;error?:string}){
 return <>
  <div className="interactive-status" role="status" aria-live="polite"><span className={'status-dot '+state}/><strong>{interactiveStatusTitle(state)}</strong>{busy&&<span>{busy}…</span>}</div>
  {error&&<div className="alert" role="alert">{error}</div>}
 </>
}
