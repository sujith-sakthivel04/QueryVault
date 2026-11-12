import {expect,test,vi} from 'vitest'
import {api,ApiError,money} from './api'
test('integer cents render exactly',()=>{expect(money(35)).toBe('$0.35');expect(money(2000)).toBe('$20.00')})
test('failed quotes propagate actionable errors',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,json:async()=>({detail:'Quote expired'})}));await expect(api('/execute',{quote_id:'expired'})).rejects.toThrow('Quote expired');vi.unstubAllGlobals()})

test('non-JSON service outages give useful errors without exposing response content',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:503,json:async()=>{throw new SyntaxError('private backend HTML')}}));try{await expect(api('/sessions')).rejects.toThrow('HTTP 503');await expect(api('/sessions')).rejects.not.toThrow('private backend')}finally{vi.unstubAllGlobals()}})

test('unexpected JSON error shape retains HTTP context',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:502,json:async()=>null}));try{await expect(api('/sessions')).rejects.toThrow('HTTP 502')}finally{vi.unstubAllGlobals()}})

test('structured provider outage code is preserved for truthful UI feedback',async()=>{vi.stubGlobal('fetch',vi.fn().mockResolvedValue({ok:false,status:503,json:async()=>({detail:{code:'provider_unavailable',message:'Planner unavailable; no query executed.'}})}));try{await expect(api('/interactive/plan',{})).rejects.toMatchObject({name:'ApiError',status:503,code:'provider_unavailable',message:'Planner unavailable; no query executed.'});expect(ApiError).toBeDefined()}finally{vi.unstubAllGlobals()}})
