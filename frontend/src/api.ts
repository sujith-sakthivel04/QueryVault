export const money=(cents:number)=>new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(cents/100)
export class ApiError extends Error{
 constructor(message:string,readonly status:number,readonly code?:string){super(message);this.name='ApiError'}
}
export async function api(path:string,body?:unknown){
 const response=await fetch(path,{credentials:'same-origin',...(body!==undefined?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
 let data;
 try{data=await response.json()}catch{throw new ApiError(`Service returned an unreadable response (HTTP ${response.status}). Check service health and session history before retrying.`,response.status)}
 if(!response.ok){const message=typeof data?.detail==='string'?data.detail:typeof data?.detail?.message==='string'?data.detail.message:`Request failed (HTTP ${response.status}). Check the request and session history before retrying.`;throw new ApiError(message,response.status,typeof data?.detail?.code==='string'?data.detail.code:undefined)} return data;
}
