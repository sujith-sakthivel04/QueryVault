"""Transactional binding quotes, reservations and single final settlement."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import uuid
import json
import hmac
import os
from psycopg.types.json import Jsonb
from db import connect, read_query
from firewall import QueryFirewall, POLICY_VERSION
from paypal_client import PayPalClient

PRICE_VERSION = "fixed-tier-v1"

class Conflict(ValueError):
    pass

def uid():
    return str(uuid.uuid4())

def price_plan(plan):
    """Published fixed tiers; estimated cost is a classifier, never dollars."""
    cost = Decimal(str(plan["Total Cost"]))
    if not cost.is_finite() or cost < 0 or cost > 10000:
        raise Conflict("Plan exceeds maximum permitted estimated cost (10000)")
    return 35 if cost <= 50 else 70 if cost <= 200 else 140

def binding_signature(q):
    """Bind accepted commercial terms; status/result updates do not change them."""
    key=os.environ.get('LOCAL_API_KEY')
    if not key:
        raise Conflict('Quote signing key is not configured')
    fields={k:q[k] for k in ('id','session_id','owner','sql_hash','price','policy','version')}
    fields['expires_at']=q['expires_at'].astimezone(timezone.utc).isoformat()
    return hmac.new(key.encode(),json.dumps(fields,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()

def require_open(s):
    if s['state'] not in ('authorized','active'):
        raise Conflict('Session must be authorized and open')
    if not s['authorization_expires_at'] or s['authorization_expires_at']<=datetime.now(timezone.utc):
        raise Conflict('Research session authorization window has expired; settle this session')

def event(conn, sid, kind, cents=0, quote_id=None, detail=None):
    conn.execute("INSERT INTO ledger(session_id,quote_id,event,cents,detail) VALUES(%s,%s,%s,%s,%s)",
                 (sid, quote_id, kind, cents, Jsonb(detail or {})))

def session(conn, sid, owner, lock=False):
    row = conn.execute("SELECT * FROM sessions WHERE id=%s AND owner=%s" + (" FOR UPDATE" if lock else ""), (sid,owner)).fetchone()
    if not row:
        raise Conflict("Session not found")
    return row

class Engine:
    def __init__(self, payment_factory=PayPalClient):
        self.payment_factory = payment_factory
        self.firewall = QueryFirewall()

    def get(self, sid, owner):
        with connect() as conn:
            return session(conn,sid,owner)

    def fail(self, sid, error):
        with connect() as conn:
            conn.execute("UPDATE sessions SET state='reconciliation_required',error=%s WHERE id=%s", (str(error),sid))
            event(conn,sid,"reconciliation_required",detail={"error":str(error)})

    def create(self, owner):
        # Check credentials before creating a durable attempt; no offline payment substitution.
        with self.payment_factory() as pay:
            sid, request = uid(), uid()
            with connect() as conn:
                conn.execute("INSERT INTO sessions(id,owner,state,budget,request_id) VALUES(%s,%s,'created',2000,%s)", (sid,owner,request))
                event(conn,sid,"created")
            try:
                order, url = pay.create_session_hold(Decimal("20.00"), request_id=request)
                with connect() as conn:
                    conn.execute("UPDATE sessions SET order_id=%s,approval_url=%s,state='awaiting_approval' WHERE id=%s", (order,url,sid))
                    event(conn,sid,"awaiting_approval",detail={"order_id":order,"request_id":request})
            except Exception as exc:
                self.fail(sid,exc)
            return self.get(sid,owner)

    def authorize(self, sid, owner):
        with connect() as conn:
            s = session(conn,sid,owner,True)
            if s["state"] in ("authorized","active","settling","settled","voided"):
                return s
            if s["state"] != "awaiting_approval":
                raise Conflict("Authorization requires awaiting_approval; reconcile uncertain attempts")
            with self.payment_factory() as pay:
                order = pay.get_order(s["order_id"])
            if order.get("status") != "APPROVED":
                raise Conflict("Buyer approval has not been verified by PayPal")
            conn.execute("UPDATE sessions SET state='authorizing' WHERE id=%s", (sid,))
            event(conn,sid,"authorizing",detail={"request_id":sid+"-auth"})
        try:
            with self.payment_factory() as pay:
                aid = pay.authorize_order(s["order_id"],request_id=sid+"-auth")
                with connect() as conn:
                    conn.execute("UPDATE sessions SET authorization_id=%s WHERE id=%s",(aid,sid))
                auth = pay.get_authorization(aid)
                if auth.get("status") != "CREATED" or auth.get("amount") != {"currency_code":"USD","value":"20.00"}:
                    raise Conflict("Authorization amount/status mismatch")
            with connect() as conn:
                conn.execute("UPDATE sessions SET authorization_id=%s,state='authorized',authorization_expires_at=now()+interval '1 hour' WHERE id=%s", (aid,sid))
                event(conn,sid,"authorized",detail={"authorization_id":aid})
        except Exception as exc:
            self.fail(sid,exc)
        return self.get(sid,owner)

    def quote(self, sid, owner, sql):
        with connect() as conn:
            require_open(session(conn,sid,owner))
        try:
            approved = self.firewall.validate(sql)
        except ValueError as exc:
            with connect() as conn:
                session(conn,sid,owner)
                event(conn,sid,"security_rejection",detail={"reason":str(exc)})
            raise
        plan = read_query(approved,explain=True)
        summary = {k:plan[k] for k in ("Node Type","Total Cost","Plan Rows","Plan Width")}
        price = price_plan(plan)
        with connect() as conn:
            s = session(conn,sid,owner,True)
            require_open(s)
            q = conn.execute("INSERT INTO quotes(id,session_id,owner,sql,sql_hash,policy,price,version,expires_at,plan) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (uid(),sid,owner,approved,hashlib.sha256(approved.encode()).hexdigest(),POLICY_VERSION,price,PRICE_VERSION,datetime.now(timezone.utc)+timedelta(minutes=5),Jsonb(summary))).fetchone()
            q['binding_signature']=binding_signature(q)
            conn.execute('UPDATE quotes SET binding_signature=%s WHERE id=%s',(q['binding_signature'],q['id']))
            event(conn,sid,"quoted",price,q["id"],detail={'sql_hash':q['sql_hash'],'policy':POLICY_VERSION,'version':PRICE_VERSION,'maximum_charge_cents':price})
            return {**q,"limits":{"rows":100,"statement_ms":2000,"billable":"nonempty successful result"}}

    def execute(self, qid, owner, *, max_price_cents=None, sql_hash=None):
        with connect() as conn:
            ref = conn.execute("SELECT session_id FROM quotes WHERE id=%s AND owner=%s",(qid,owner)).fetchone()
            if not ref:
                raise Conflict("Quote not found")
            sid = ref["session_id"]
            s = session(conn,sid,owner,True)
            q = conn.execute("SELECT * FROM quotes WHERE id=%s FOR UPDATE",(qid,)).fetchone()
            if max_price_cents is not None and (type(max_price_cents) is not int or max_price_cents<q['price']):
                raise Conflict('Quote exceeds the explicitly accepted price ceiling')
            if sql_hash is not None and sql_hash!=q['sql_hash']:
                raise Conflict('Accepted SQL hash differs from the quote')
            if q["state"] == "completed":
                return q["result"]
            if q["state"] != "quoted" or s["state"] not in ("authorized","active"):
                raise Conflict("Quote already used or session closed")
            if not s["authorization_expires_at"] or s["authorization_expires_at"] <= datetime.now(timezone.utc):
                raise Conflict("Research session authorization window has expired; settle this session")
            if q["expires_at"] <= datetime.now(timezone.utc) or q["policy"] != POLICY_VERSION or q["version"] != PRICE_VERSION:
                raise Conflict("Quote expired or policy changed")
            if hashlib.sha256(q["sql"].encode()).hexdigest() != q["sql_hash"]:
                raise Conflict("SQL binding changed")
            if not q['binding_signature'] or not hmac.compare_digest(q['binding_signature'],binding_signature(q)):
                raise Conflict('Quoted commercial terms changed; request a fresh quote')
            self.firewall.validate(q['sql'])
            if s["spent"]+s["reserved"]+q["price"] > s["budget"]:
                raise Conflict("Insufficient unreserved budget")
            conn.execute("UPDATE sessions SET reserved=reserved+%s,state='active' WHERE id=%s",(q["price"],sid))
            conn.execute("UPDATE quotes SET state='running',started_at=now() WHERE id=%s",(qid,))
            event(conn,sid,"reserved",q["price"],qid,detail={'maximum_charge_cents':q['price']})
        try:
            rows = read_query(q["sql"])
            result = {"rows":json.loads(json.dumps(rows,default=str)),"charged_cents":q["price"] if rows else 0,"quote_id":qid}
        except Exception:
            with connect() as conn:
                session(conn,sid,owner,True)
                current=conn.execute('SELECT state FROM quotes WHERE id=%s FOR UPDATE',(qid,)).fetchone()
                if current['state']=='running':
                    conn.execute("UPDATE sessions SET reserved=reserved-%s WHERE id=%s",(q["price"],sid))
                    conn.execute("UPDATE quotes SET state='failed' WHERE id=%s",(qid,))
                    event(conn,sid,"released_failure",q["price"],qid)
            raise
        with connect() as conn:
            session(conn,sid,owner,True)
            current=conn.execute('SELECT state FROM quotes WHERE id=%s FOR UPDATE',(qid,)).fetchone()
            if current['state']!='running':
                raise Conflict('Query reservation was recovered; stale worker cannot charge or deliver results')
            conn.execute("UPDATE sessions SET reserved=reserved-%s,spent=spent+%s WHERE id=%s",(q["price"],result["charged_cents"],sid))
            conn.execute("UPDATE quotes SET state='completed',result=%s WHERE id=%s",(Jsonb(result),qid))
            event(conn,sid,"charged" if rows else "released_empty",result["charged_cents"],qid)
        return result

    def settle(self, sid, owner):
        with connect() as conn:
            s = session(conn,sid,owner,True)
            if s["state"] in ("settled","voided","reconciliation_required"):
                return s
            if s["state"] not in ("authorized","active","settling"):
                raise Conflict("Session cannot settle in its current state")
            conn.execute("UPDATE sessions SET state='settling' WHERE id=%s",(sid,))
            if s["reserved"]:
                return {**s,"state":"settling","waiting_for_queries":True}
            if s["payment"]:
                return {**s,"state":"settling"}
            total = conn.execute("SELECT COALESCE(SUM(cents),0) AS n FROM ledger WHERE session_id=%s AND event='charged'",(sid,)).fetchone()["n"]
            if total != s["spent"]:
                message='Ledger spend mismatch; settlement blocked before any PayPal call'
                failed=conn.execute("UPDATE sessions SET state='reconciliation_required',error=%s WHERE id=%s RETURNING *",(message,sid)).fetchone()
                event(conn,sid,'reconciliation_required',detail={'error':message,'ledger_cents':int(total),'session_cents':s['spent']})
                return failed
            conn.execute("UPDATE sessions SET payment=%s WHERE id=%s",(Jsonb({"claimed":True,"request_id":sid+"-settle"}),sid))
            event(conn,sid,"settlement_claimed",total,detail={"request_id":sid+"-settle"})
        try:
            with self.payment_factory() as pay:
                if total == 0:
                    pay.void_session(s["authorization_id"],request_id=sid+"-settle")
                    record = pay.get_authorization(s["authorization_id"])
                    if record.get("status") != "VOIDED":
                        raise Conflict("Void not independently verified")
                    state, capture_id = "voided", None
                else:
                    result = pay.capture_session_funds(s["authorization_id"],Decimal(total)/100,request_id=sid+"-settle")
                    capture_id = result["id"]
                    with connect() as conn:
                        conn.execute("UPDATE sessions SET capture_id=%s WHERE id=%s",(capture_id,sid))
                    record = pay.get_capture(capture_id)
                    expected = {"currency_code":"USD","value":f"{Decimal(total)/100:.2f}"}
                    if record.get("status") != "COMPLETED" or record.get("amount") != expected:
                        raise Conflict("Capture pending, failed, or amount mismatch; reconciliation required")
                    state = "settled"
            with connect() as conn:
                conn.execute("UPDATE sessions SET state=%s,capture_id=%s,payment=%s,error=NULL WHERE id=%s",(state,capture_id,Jsonb(record),sid))
                event(conn,sid,state,total,detail=record)
        except Exception as exc:
            self.fail(sid,exc)
        return self.get(sid,owner)

    def ledger(self,sid,owner):
        with connect() as conn:
            session(conn,sid,owner)
            return conn.execute("SELECT * FROM ledger WHERE session_id=%s ORDER BY id",(sid,)).fetchall()

    def history(self,sid,owner):
        with connect() as conn:
            session(conn,sid,owner)
            return conn.execute('SELECT id,sql,sql_hash,price,policy,version,expires_at,plan,state,result FROM quotes WHERE session_id=%s AND owner=%s ORDER BY expires_at DESC,id',(sid,owner)).fetchall()

    def recover_stale_queries(self,sid,owner):
        """Fence abandoned workers after a 30s grace, release only their holds.

        A late worker must recheck its quote state before charging/delivering.
        This never retries SQL or any PayPal operation.
        """
        with connect() as conn:
            s=session(conn,sid,owner,True)
            if s['state'] not in ('authorized','active','settling'):
                raise Conflict('Only open or draining sessions can recover query reservations')
            stale=conn.execute("SELECT id,price FROM quotes WHERE session_id=%s AND state='running' AND started_at<now()-interval '30 seconds' FOR UPDATE",(sid,)).fetchall()
            total=sum(q['price'] for q in stale)
            if total>s['reserved']:
                raise Conflict('Reservation accounting mismatch; recovery blocked')
            for q in stale:
                conn.execute("UPDATE quotes SET state='failed',result=%s WHERE id=%s",(Jsonb({'error':'Abandoned reservation recovered; no result delivered or charge applied'}),q['id']))
                event(conn,sid,'released_recovered',q['price'],q['id'])
            conn.execute('UPDATE sessions SET reserved=reserved-%s WHERE id=%s',(total,sid))
            return {'session_id':sid,'recovered_queries':len(stale),'released_cents':total,'payments_attempted':0}

    def start_agent_run(self,sid,owner,objective):
        with connect() as conn:
            require_open(session(conn,sid,owner,True))
            run=uid()
            conn.execute("INSERT INTO agent_runs(id,session_id,owner,objective,state) VALUES(%s,%s,%s,%s,'running')",(run,sid,owner,objective))
            event(conn,sid,'agent_started',detail={'run_id':run})
            return run

    def finish_agent_run(self,run,sid,owner,result=None,error=None):
        state='failed' if error else 'completed'
        with connect() as conn:
            session(conn,sid,owner)
            conn.execute('UPDATE agent_runs SET state=%s,result=%s,error=%s,finished_at=now() WHERE id=%s AND owner=%s',(state,Jsonb(json.loads(json.dumps(result,default=str))) if result else None,error,run,owner))
            event(conn,sid,'agent_'+state,detail={'run_id':run})

    def agent_history(self,sid,owner):
        with connect() as conn:
            session(conn,sid,owner)
            return conn.execute('SELECT * FROM agent_runs WHERE session_id=%s AND owner=%s ORDER BY created_at DESC',(sid,owner)).fetchall()

    def reconcile(self,sid,owner):
        """Read PayPal independently; never retry an uncertain mutation here."""
        with connect() as conn:
            s=session(conn,sid,owner,True)
            if s["state"] not in ("reconciliation_required","authorizing","settling"):
                return s
            total=conn.execute("SELECT COALESCE(SUM(cents),0) AS n FROM ledger WHERE session_id=%s AND event='charged'",(sid,)).fetchone()['n']
            if s['reserved'] or total!=s['spent']:
                raise Conflict('Reservations or inconsistent ledger prevent reconciliation')
            with self.payment_factory() as pay:
                if s["capture_id"]:
                    record=pay.get_capture(s["capture_id"])
                    expected={"currency_code":"USD","value":f"{Decimal(s['spent'])/100:.2f}"}
                    if record.get("status") != "COMPLETED" or record.get("amount") != expected:
                        raise Conflict("Capture still pending or mismatched; no payment retried")
                    state="settled"
                elif s["authorization_id"] and s["spent"]==0 and s["reserved"]==0:
                    record=pay.get_authorization(s["authorization_id"])
                    if record.get("status") != "VOIDED":
                        raise Conflict("Authorization is not independently confirmed voided; inspect PayPal")
                    state="voided"
                else:
                    raise Conflict("Uncertain mutation requires manual PayPal investigation using persisted request/order IDs; no new payment created")
            conn.execute("UPDATE sessions SET state=%s,payment=%s,error=NULL WHERE id=%s",(state,Jsonb(record),sid))
            event(conn,sid,"reconciled_"+state,s["spent"],detail=record)
        return self.get(sid,owner)
