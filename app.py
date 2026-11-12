"""Local operator workflow and an explicit restricted public-demo boundary."""
import os
import secrets
import json
import psycopg
from pathlib import Path
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from engine import Engine, Conflict, PRICE_VERSION
from firewall import PolicyError, SCHEMA
from paypal_client import PayPalClient, PayPalError
from db import connect, read_query
from engine import price_plan
from agent import research
from settings import Settings, ConfigurationError
from public_demo import TEMPLATES, DemoAdmission, verify_reader
from demo_quota import DemoQuotaStore, QuotaError, visitor_digest
from interactive_api import router as interactive_router
from contextlib import asynccontextmanager
from ipaddress import ip_address
from urllib.parse import urlsplit
from typing import Literal
import logging

engine = Engine()
OWNER = "local-operator"
logger = logging.getLogger('queryvault')
PUBLIC_ROUTES = {('GET', p) for p in ('/api/config','/health','/health/live','/health/ready','/catalogue','/evaluation','/demo/evidence')} | {('POST','/demo/query')}
INTERACTIVE_ROUTES = {('GET','/interactive/state')} | {('POST',p) for p in ('/interactive/plan','/interactive/accept','/interactive/execute')}

def local_peer(request):
    host = request.client.host if request.client else ''
    if host == 'testclient':  # ASGI TestClient's synthetic socket, never a TCP peer.
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False

def boundary(request:Request):
    cfg=request.app.state.settings
    if cfg.public_mode:
        allowed=PUBLIC_ROUTES | (INTERACTIVE_ROUTES if cfg.public_interactive else set())
        path=request.url.path
        plan_read=request.method=='GET' and path.startswith('/interactive/plans/') and len(path.rsplit('/',1)[-1])<=80
        if (request.method,request.url.path) not in allowed and not plan_read:
            raise HTTPException(403,'Operator and payment workflows are disabled in public mode')

router = APIRouter(dependencies=[Depends(boundary)])

def owner(request:Request):
    if request.app.state.settings.public_mode or not local_peer(request):
        raise HTTPException(403,'Operator access is available only on the local loopback workflow')
    key = os.getenv("LOCAL_API_KEY", "")
    supplied = request.cookies.get("qv_local") or request.headers.get("X-API-Key", "")
    if not key or not secrets.compare_digest(key,supplied):
        raise HTTPException(401,"Open the local workspace first")
    return OWNER

def viewer(request:Request):
    return 'public-synthetic-demo' if request.app.state.settings.public_mode else owner(request)

@router.post("/api/local-login")
def login(request:Request):
    # Never grant operator access to a remote socket or a forwarded client IP.
    if request.app.state.settings.public_mode or not local_peer(request):
        raise HTTPException(403,"Local operator bootstrap is disabled here")
    if request.headers.get("origin") != str(request.base_url).rstrip('/'):
        raise HTTPException(403,"Local same-origin browser required")
    if not os.getenv('LOCAL_API_KEY'):
        raise HTTPException(503,'Local environment is not initialized. Run python bootstrap.py.')
    response = JSONResponse({"mode":"local single-operator"})
    response.set_cookie("qv_local",os.environ["LOCAL_API_KEY"],httponly=True,samesite="strict")
    return response

async def conflict(request,exc):
    return JSONResponse({"detail":str(exc)},409)

async def policy(request,exc):
    return JSONResponse({"detail":str(exc)},422)

async def invalid(request,exc):
    return JSONResponse({"detail":str(exc)},422)

async def payment_error(request,exc):
    return JSONResponse({"detail":"PayPal request failed; inspect diagnostics and reconciliation state","debug_id":exc.debug_id},502)

async def database_error(request,exc):
    if isinstance(exc,psycopg.errors.QueryCanceled):
        return JSONResponse({'detail':'Query exceeded its execution limit. Check session history before retrying.'},504)
    return JSONResponse({'detail':'Database operation could not complete. Check service health and query history; no automatic retry was made.'},503)

class QuoteRequest(BaseModel):
    session_id:str
    sql:str = Field(min_length=1,max_length=12000)

class ExecuteRequest(BaseModel):
    quote_id:str
    max_price_cents:int | None = Field(default=None,ge=0,le=2000,strict=True)
    sql_hash:str | None = Field(default=None,pattern=r'^[0-9a-f]{64}$')

class AgentRequest(BaseModel):
    session_id:str
    objective:str = Field(min_length=5,max_length=2000)

class DemoQuery(BaseModel):
    sql:str = Field(min_length=1,max_length=12000)

class PublicDemoQuery(BaseModel):
    model_config = {"extra":"forbid"}
    template: Literal['port_delays','shipment_count']

@router.get('/api/config')
def configuration(request:Request):
    cfg=request.app.state.settings
    public=cfg.public_mode
    interactive_available=False
    if cfg.public_interactive and cfg.interactive_enabled:
        try: interactive_available=not request.app.state.interactive_store.kill_switch_active(cfg.quota_kill_file)
        except Exception: interactive_available=False
    return {'mode':cfg.mode,'operator_workflows':not public,
            'live_ai':not public,'interactive_ai':interactive_available,'payments':not public,
            'preview':{'template':'port_delays','sql':TEMPLATES['port_delays']} if public else None}

@router.post("/demo/query",openapi_extra={'requestBody':{'required':True,'content':{'application/json':{'schema':{'type':'object','properties':{'sql':{'type':'string','minLength':1,'maxLength':12000}},'required':['sql']}}}}})
async def demo_query(request:Request, who=Depends(viewer)):
    cfg=request.app.state.settings
    payload=await request.json()
    if cfg.public_demo or cfg.public_interactive:
        try:
            body=PublicDemoQuery.model_validate(payload)
        except ValueError:
            raise HTTPException(422,'Public demo accepts only a named synthetic template; SQL and extra fields are forbidden') from None
        admission=request.app.state.admission
        slot=None
        if cfg.public_interactive:
            token=request.cookies.get('qv_demo_visitor','')
            if not token or len(token)>100:
                raise HTTPException(401,'Open the interactive workspace before using a preview')
            digest=visitor_digest(token)
            try:
                request.app.state.interactive_store.state(digest)
                request.app.state.interactive_store.admit_http(digest)
                slot=request.app.state.interactive_store.reserve_preview(digest)
            except QuotaError as exc:
                raise HTTPException(exc.status,detail={'code':exc.code,'message':exc.detail}) from None
        else:
            if not admission.admit():
                raise HTTPException(429,'Public demo request limit reached; try again later',headers={'Retry-After':'60'})
            if not admission.slots.acquire(blocking=False):
                raise HTTPException(503,'Public demo is busy; try again later',headers={'Retry-After':'2'})
        from starlette.concurrency import run_in_threadpool
        def run():
            if cfg.public_interactive:
                verify_reader(cfg.reader_url,expected_database='queryvault_interactive_demo',expected_role='qv_interactive_reader')
            else:
                verify_reader(cfg.reader_url)
            approved=engine.firewall.validate(TEMPLATES[body.template])
            plan=read_query(approved,explain=True,reader_url=cfg.reader_url)
            label=('restricted public synthetic preview; no financial session or live AI' if cfg.public_demo
                   else 'interactive-mode free synthetic preview; no financial session, AI decision, or payment')
            return {'mode':label,'rows':read_query(approved,reader_url=cfg.reader_url),'charged_cents':0,'advisory_price_cents':price_plan(plan),'sql':approved}
        try:
            return await run_in_threadpool(run)
        except ValueError:
            raise HTTPException(503,'Public synthetic database is not ready') from None
        finally:
            if slot:
                request.app.state.interactive_store.release_slot(slot)
            if cfg.public_demo:
                admission.slots.release()
    try:
        body=DemoQuery.model_validate(payload)
    except ValueError:
        raise HTTPException(422,'SQL must contain 1–12000 characters') from None
    from starlette.concurrency import run_in_threadpool
    def run_local():
        approved=engine.firewall.validate(body.sql)
        plan=read_query(approved,explain=True)
        return {'mode':'free synthetic data preview; no financial session or live AI','rows':read_query(approved),'charged_cents':0,'advisory_price_cents':price_plan(plan),'sql':approved}
    return await run_in_threadpool(run_local)

@router.get('/health/live')
def liveness():
    return {'status':'alive'}

@router.get('/health/ready')
def readiness(request:Request):
    try:
        if request.app.state.stopping:
            raise ValueError('Stopping')
        cfg=request.app.state.settings
        if cfg.public_demo:
            verify_reader(cfg.reader_url)
        elif cfg.public_interactive:
            verify_reader(cfg.reader_url,expected_database='queryvault_interactive_demo',expected_role='qv_interactive_reader')
        else:
            with connect() as conn: conn.execute('SELECT 1')
        return {'status':'ready'}
    except Exception:
        return JSONResponse({'status':'unavailable'},503)

@router.get("/health")
def health(request:Request):
    try:
        cfg=request.app.state.settings
        if cfg.public_demo:
            verify_reader(cfg.reader_url)
        elif cfg.public_interactive:
            verify_reader(cfg.reader_url,expected_database='queryvault_interactive_demo',expected_role='qv_interactive_reader')
        else:
            with connect() as conn: conn.execute('SELECT 1')
        database='connected'
    except Exception:
        database='unavailable'
    cfg=request.app.state.settings
    public=cfg.public_mode
    if cfg.public_demo: ai='disabled_in_public_demo'
    elif cfg.public_interactive:
        try: ai='interactive_available' if cfg.interactive_enabled and not request.app.state.interactive_store.kill_switch_active(cfg.quota_kill_file) else 'interactive_disabled'
        except Exception: ai='interactive_disabled'
    else: ai='groq_configured' if os.getenv("GROQ_API_KEY") else 'offline'
    paypal_status='disabled_in_public_demo' if cfg.public_demo else 'disabled_in_public_interactive' if cfg.public_interactive else 'sandbox_configured' if os.getenv("PAYPAL_CLIENT_ID") and os.getenv("PAYPAL_SECRET") else 'credentials_missing'
    return {"database":database,"mode":cfg.mode,"paypal":paypal_status,"ai":ai,"dataset":"synthetic logistics, October 2026","pricing":{"version":PRICE_VERSION,"tiers_cents":[35,70,140],"cost_thresholds":[50,200,10000],"billable":"nonempty successful result","quote_ttl_seconds":300}}

@router.post("/sessions")
def create(who=Depends(owner)):
    return engine.create(who)

@router.get("/sessions")
def listing(who=Depends(owner)):
    with connect() as conn:
        return conn.execute("SELECT * FROM sessions WHERE owner=%s ORDER BY id",(who,)).fetchall()

@router.get("/sessions/{sid}")
def get(sid:str,who=Depends(owner)):
    return engine.get(sid,who)

@router.post("/sessions/{sid}/authorize")
def authorize(sid:str,who=Depends(owner)):
    return engine.authorize(sid,who)

@router.post("/sessions/{sid}/settle")
def settle(sid:str,who=Depends(owner)):
    return engine.settle(sid,who)

@router.get("/sessions/{sid}/ledger")
def ledger(sid:str,who=Depends(owner)):
    return engine.ledger(sid,who)

@router.post("/sessions/{sid}/reconcile")
def reconcile(sid:str,who=Depends(owner)):
    return engine.reconcile(sid,who)

@router.post("/quote")
def quote(body:QuoteRequest,who=Depends(owner)):
    return engine.quote(body.session_id,who,body.sql)

@router.post("/execute")
def execute(body:ExecuteRequest,who=Depends(owner)):
    return engine.execute(body.quote_id,who,max_price_cents=body.max_price_cents,sql_hash=body.sql_hash)

@router.post("/agent")
def agent(body:AgentRequest,who=Depends(owner)):
    run=engine.start_agent_run(body.session_id,who,body.objective)
    try:
        result=research(engine,body.session_id,who,body.objective)
        engine.finish_agent_run(run,body.session_id,who,result=result)
        return {**result,'run_id':run}
    except Exception:
        engine.finish_agent_run(run,body.session_id,who,error='Agent provider or execution failed; inspect the query ledger before retrying')
        raise HTTPException(502,'Agent failed; any completed query charges remain in the durable ledger')

@router.get('/sessions/{sid}/queries')
def queries(sid:str,who=Depends(owner)):
    return engine.history(sid,who)

@router.get('/sessions/{sid}/agent-runs')
def agent_runs(sid:str,who=Depends(owner)):
    return engine.agent_history(sid,who)

@router.post('/sessions/{sid}/recover-queries')
def recover_queries(sid:str,who=Depends(owner)):
    return engine.recover_stale_queries(sid,who)

@router.get("/catalogue")
def catalogue(who=Depends(viewer)):
    return {"schema":SCHEMA,"provenance":"600 reproducible synthetic records; not live enterprise data","policy":"SELECT only; approved tables/columns/functions; max 100 rows; 2s statement timeout"}

@router.get("/evaluation")
def evaluation(request:Request,who=Depends(viewer)):
    path=Path(__file__).parent/'evaluation.json'
    data=json.loads(path.read_text()) if path.exists() else {'status':'not run'}
    if request.app.state.settings.public_mode:
        return {k:data[k] for k in ('legitimate_accepted','security_rejections','known_answers_correct',) if k in data} | {'label':'Historical recorded evaluation; no model call is made by viewing it'}
    return data

@router.get('/demo/evidence')
def historical_evidence(who=Depends(viewer)):
    return json.loads((Path(__file__).parent/'demo-evidence.json').read_text())

@router.get("/paypal/return", response_class=HTMLResponse, include_in_schema=False)
@router.get("/paypal/cancel", response_class=HTMLResponse, include_in_schema=False)
def paypal_landing():
    # This GET performs no financial mutation and does not trust callback fields.
    return HTMLResponse((Path(__file__).parent/'checkout_return.html').read_text(encoding='utf-8'),
                        headers={"Cache-Control":"no-store","X-Frame-Options":"DENY"})

@router.get("/api/paypal/return-status")
def checkout_status(token:str,who=Depends(owner)):
    token=PayPalClient._resource_id(token)
    with connect() as conn:
        s=conn.execute("SELECT id,state,spent,reserved,capture_id FROM sessions WHERE order_id=%s AND owner=%s",(token,who)).fetchone()
    if not s:
        raise HTTPException(404,"Order is not associated with this workspace")
    with engine.payment_factory() as pay:
        order=pay.get_order(token)
        authorizations=[]
        for unit in order.get('purchase_units',[]):
            for auth in unit.get('payments',{}).get('authorizations',[]):
                # An Orders response can lag payment state; verify separately.
                verified=pay.get_authorization(auth['id'])
                authorizations.append({"id":verified['id'],"status":verified['status'],"amount":verified.get('amount')})
    return {"order_id":token,"order_status":order.get('status'),"buyer_approval_verified":order.get('status')=='APPROVED',"session":s,"authorizations":authorizations,"verification_source":"PayPal Orders v2 GET and Payments v2 authorization GET; redirect parameters are not approval evidence"}

RESERVED = {'api','health','sessions','quote','execute','agent','catalogue','evaluation','demo','interactive','paypal','docs','redoc','openapi.json'}

class SPAFiles(StaticFiles):
    async def get_response(self,path,scope):
        # Starlette supplies OS-native separators (backslashes on Windows).
        clean='' if path=='.' else path.replace('\\','/')
        first=clean.lstrip('/').split('/')[0]
        if first in RESERVED or any(part.startswith('.') for part in clean.split('/') if part):
            raise HTTPException(404,'API route not found')
        try:
            return await super().get_response(path,scope)
        except Exception as exc:
            if getattr(exc,'status_code',None)!=404 or scope['method'] not in ('GET','HEAD') or Path(path).suffix or first=='assets':
                raise
            return await super().get_response('index.html',scope)

@asynccontextmanager
async def lifespan(application):
    cfg=application.state.settings
    if cfg.public_mode:
        if not (cfg.frontend/'index.html').is_file():
            raise ConfigurationError('Build the frontend before starting public mode')
        evidence=json.loads((Path(__file__).parent/'demo-evidence.json').read_text())
        if 'HISTORICAL' not in evidence.get('label',''):
            raise ConfigurationError('Public evidence must be labeled historical')
    if cfg.public_interactive:
        try:
            application.state.interactive_store.validate()
            verify_reader(cfg.reader_url,expected_database='queryvault_interactive_demo',expected_role='qv_interactive_reader')
        except Exception:
            logger.error('Interactive mode failed closed during durable-state or reader verification')
            raise ConfigurationError('Interactive mode requires durable quotas and its dedicated synthetic reader') from None
    application.state.stopping=False
    logger.info('QueryVault started in %s mode',cfg.mode)
    try:
        yield
    finally:
        application.state.stopping=True
        logger.info('QueryVault stopped; no financial operation was retried')


def create_app(config=None):
    cfg=config or Settings.from_env()
    application=FastAPI(title='QueryVault',version='0.1.0',lifespan=lifespan,
                        docs_url=None if cfg.public_mode else '/docs',
                        redoc_url=None if cfg.public_mode else '/redoc',
                        openapi_url=None if cfg.public_mode else '/openapi.json')
    application.state.settings=cfg
    application.state.stopping=False
    application.state.admission=DemoAdmission()
    application.state.interactive_store=DemoQuotaStore(cfg.quota_path) if cfg.public_interactive and cfg.quota_path else None
    @application.middleware('http')
    async def security(request:Request,call_next):
        def finish(response):
            response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY','Cache-Control':'no-store'})
            if cfg.public_mode:
                response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                if urlsplit(cfg.public_origin).scheme=='https':
                    response.headers['Strict-Transport-Security']='max-age=31536000'
            return response
        expected=cfg.public_origin if cfg.public_mode else str(request.base_url).rstrip('/')
        if request.method not in ('GET','HEAD','OPTIONS'):
            if cfg.public_interactive and request.url.path.startswith('/interactive/') and request.headers.get('origin')!=cfg.public_origin:
                return finish(JSONResponse({'detail':'Exact same-origin request required'},403))
            if request.headers.get('origin') and request.headers['origin']!=expected:
                return finish(JSONResponse({'detail':'Cross-origin writes are forbidden'},403))
            if request.headers.get('sec-fetch-site')=='cross-site':
                return finish(JSONResponse({'detail':'Cross-site access forbidden'},403))
            if cfg.public_mode:
                chunks=[];size=0
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>16384:
                        return finish(JSONResponse({'detail':'Request body exceeds public-demo limit'},413))
                    chunks.append(chunk)
                request._body=b''.join(chunks)
        try:
            return finish(await call_next(request))
        except Exception as exc:
            # No bodies, headers, URLs, SQL, DSNs or provider responses in logs.
            logger.error('Unhandled request failure: %s',type(exc).__name__)
            return finish(JSONResponse({'detail':'Service request failed; check readiness and session history before retrying'},500))
    application.add_middleware(TrustedHostMiddleware,allowed_hosts=cfg.allowed_hosts)
    for kind,handler in ((Conflict,conflict),(PolicyError,policy),(ValueError,invalid),(PayPalError,payment_error),(psycopg.Error,database_error)):
        application.add_exception_handler(kind,handler)
    if cfg.public_interactive:
        application.add_exception_handler(QuotaError,lambda request,exc: JSONResponse({'detail':{'code':exc.code,'message':exc.detail}},status_code=exc.status))
        application.include_router(interactive_router)
    application.include_router(router)
    if cfg.frontend.exists():
        application.mount('/',SPAFiles(directory=cfg.frontend,html=True),name='workspace')
    return application

app=create_app()
