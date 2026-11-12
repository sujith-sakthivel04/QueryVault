export type Session = {id:string;state:string;budget:number;spent:number;reserved:number;approval_url?:string;order_id?:string;authorization_id?:string;capture_id?:string;error?:string;payment?:unknown};

export function verifiedCaptureCents(session?:Session):number|null {
 const p=session?.payment as {status?:string;amount?:{currency_code?:string;value?:string}}|undefined;
 if(session?.state!=='settled'||p?.status!=='COMPLETED'||p.amount?.currency_code!=='USD'||!/^\d+\.\d{2}$/.test(p.amount.value||''))return null;
 const [d,c]=p.amount.value!.split('.');const cents=Number(d)*100+Number(c);
 return Number.isSafeInteger(cents)&&cents===session.spent?cents:null;
}

export function sessionView(session?:Session){
 const closed=!!session&&['settled','voided'].includes(session.state);
 return {closed,canSettle:!!session&&['authorized','active','settling'].includes(session.state),
  budgetLabel:closed?'Unspent session budget':'Available query budget',
  budgetValue:session?session.budget-session.spent-(closed?0:session.reserved):null,
  title:session?.state==='settled'?'Session settled':session?.state==='voided'?'Authorization voided':session?.state==='settling'?'Settlement in progress':'Authorization & settlement',
  capturedCents:verifiedCaptureCents(session)};
}
