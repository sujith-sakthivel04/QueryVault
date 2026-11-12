import {money} from './api';
import {Session,sessionView} from './presentation';
type HistoricalEvidence={captured_cents:number;capture_status:string;verified_date:string};

export default function SessionStatus({session,evidence}:{session?:Session;evidence?:HistoricalEvidence}){
 const view=sessionView(session);
 if(!view.closed&&!evidence)return null;
 const historicalOnly=!session&&!!evidence;
 return <div className="settled-state" role="status">
  <span className="badge">{historicalOnly?'HISTORICAL EVIDENCE · NOT LIVE':session?.state==='settled'?'SETTLED · SAVED VERIFICATION':'VOIDED · SAVED VERIFICATION'}</span>
  <h3>{historicalOnly?'Earlier session settled':view.title}</h3>
  <p>{historicalOnly?`Recorded ${evidence!.verified_date}: PayPal capture ${evidence!.capture_status}, ${money(evidence!.captured_cents)}. No current checkout or payment was created.`:view.capturedCents!==null?`PayPal capture independently recorded as COMPLETED: ${money(view.capturedCents)}.`:session?.state==='voided'?'Authorization status independently recorded as VOIDED. No session charge is recorded.':'Settlement is recorded. Inspect the saved verification details for the provider status.'}</p>
  <strong>No additional payment is required to inspect this record.</strong>
 </div>
}
