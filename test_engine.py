from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import patch
import pytest
from psycopg.types.json import Jsonb
from db import connect
from engine import Engine, Conflict, uid, price_plan

class FakePayPal:
    captures = 0
    voids = 0
    captured = "0.00"
    mismatch = False
    timeout = False
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def create_session_hold(self,amount,**kwargs): return "ORDER1","https://sandbox.example/approve"
    def get_order(self,oid): return {"status":"APPROVED"}
    def authorize_order(self,oid,**kwargs): return "AUTH1"
    def get_authorization(self,aid): return {"status":"VOIDED" if self.voids else "CREATED","amount":{"currency_code":"USD","value":"20.00"}}
    def capture_session_funds(self,aid,amount,**kwargs):
        type(self).captures += 1
        type(self).captured = f"{amount:.2f}"
        if self.timeout: raise TimeoutError("injected ambiguous payment timeout")
        return {"id":"CAPTURE1"}
    def get_capture(self,cid): return {"id":cid,"status":"COMPLETED","amount":{"currency_code":"USD","value":"99.99" if self.mismatch else self.captured}}
    def void_session(self,aid,**kwargs): type(self).voids += 1

@pytest.fixture
def engine():
    FakePayPal.captures=FakePayPal.voids=0
    FakePayPal.mismatch=FakePayPal.timeout=False
    return Engine(FakePayPal)

def authorized(engine):
    s=engine.create("test")
    return engine.authorize(s["id"],"test")["id"]

def test_multiple_queries_and_exact_single_settlement(engine,record_property):
    sid=authorized(engine)
    for sql in ("SELECT COUNT(*) FROM shipments","SELECT * FROM ports"):
        q=engine.quote(sid,"test",sql)
        result=engine.execute(q["id"],"test")
        assert result["charged_cents"]==q["price"]
        assert engine.execute(q["id"],"test")==result
    result=engine.settle(sid,"test")
    assert result["state"]=="settled"
    assert Decimal(FakePayPal.captured)*100==result["spent"]
    engine.settle(sid,"test")
    assert FakePayPal.captures==1
    record_property('payment_mode','mock')
    record_property('expected_capture_cents',result['spent'])
    record_property('verified_capture_cents',int(Decimal(FakePayPal.captured)*100))
    record_property('capture_calls_after_duplicate_settlement',FakePayPal.captures)

def test_zero_spend_void(engine):
    sid=authorized(engine)
    assert engine.settle(sid,"test")["state"]=="voided"
    assert FakePayPal.voids==1

def test_pricing_and_expired_quotes(engine):
    assert [price_plan({"Total Cost":n}) for n in (0,50,51,200,201)]==[35,35,70,70,140]
    sid=authorized(engine)
    q=engine.quote(sid,"test","SELECT * FROM ports")
    with connect() as conn: conn.execute("UPDATE quotes SET expires_at=now()-interval '1 second' WHERE id=%s",(q["id"],))
    with pytest.raises(Conflict): engine.execute(q["id"],"test")

def test_concurrent_reservations_never_overspend(engine,record_property):
    sid=authorized(engine)
    with connect() as conn: conn.execute("UPDATE sessions SET budget=100 WHERE id=%s",(sid,))
    quotes=[engine.quote(sid,"test","SELECT * FROM ports") for _ in range(12)]
    def run(q):
        try: return engine.execute(q["id"],"test")["charged_cents"]
        except Conflict: return 0
    with ThreadPoolExecutor(max_workers=8) as pool: charges=list(pool.map(run,quotes))
    s=engine.get(sid,"test")
    assert sum(charges)==70 and s["spent"]==70 and s["reserved"]==0
    assert s["spent"]+s["reserved"]<=s["budget"]
    record_property('concurrent_requests',len(quotes))
    record_property('budget_invariant_violations',int(s['spent']+s['reserved']>s['budget']))

@pytest.mark.parametrize('fault',["timeout","mismatch"])
def test_ambiguous_payment_no_duplicate(engine,fault):
    sid=authorized(engine)
    q=engine.quote(sid,"test","SELECT * FROM ports")
    engine.execute(q["id"],"test")
    setattr(FakePayPal,fault,True)
    assert engine.settle(sid,"test")["state"]=="reconciliation_required"
    engine.settle(sid,"test")
    assert FakePayPal.captures==1

def test_failed_and_empty_queries_release_reservations(engine):
    sid=authorized(engine)
    q=engine.quote(sid,"test","SELECT * FROM ports WHERE id=999")
    assert engine.execute(q["id"],"test")["charged_cents"]==0
    q=engine.quote(sid,"test","SELECT * FROM ports")
    with patch('engine.read_query',side_effect=RuntimeError("injected query failure")):
        with pytest.raises(RuntimeError): engine.execute(q["id"],"test")
    s=engine.get(sid,"test")
    assert s["spent"]==s["reserved"]==0

def test_concurrent_settlement_claim(engine):
    sid=authorized(engine)
    q=engine.quote(sid,"test","SELECT * FROM ports")
    engine.execute(q["id"],"test")
    with ThreadPoolExecutor(max_workers=6) as pool: list(pool.map(lambda _:engine.settle(sid,"test"),range(6)))
    assert FakePayPal.captures==1

def test_owner_binding_and_append_only(engine):
    sid=authorized(engine)
    q=engine.quote(sid,"test","SELECT * FROM ports")
    with pytest.raises(Conflict): engine.execute(q["id"],"other")
    with connect() as conn:
        with pytest.raises(Exception): conn.execute("DELETE FROM ledger WHERE session_id=%s",(sid,))

def test_expired_authorization_and_changed_policy(engine):
    sid=authorized(engine)
    q=engine.quote(sid,'test','SELECT * FROM ports')
    with connect() as conn: conn.execute("UPDATE sessions SET authorization_expires_at=now()-interval '1 second' WHERE id=%s",(sid,))
    with pytest.raises(Conflict): engine.execute(q['id'],'test')
    sid=authorized(engine)
    q=engine.quote(sid,'test','SELECT * FROM ports')
    with connect() as conn: conn.execute("UPDATE quotes SET policy='changed' WHERE id=%s",(q['id'],))
    with pytest.raises(Conflict): engine.execute(q['id'],'test')

def test_known_capture_can_reconcile_without_second_payment(engine):
    sid=authorized(engine)
    q=engine.quote(sid,'test','SELECT * FROM ports')
    engine.execute(q['id'],'test')
    FakePayPal.mismatch=True
    assert engine.settle(sid,'test')['state']=='reconciliation_required'
    FakePayPal.mismatch=False
    assert engine.reconcile(sid,'test')['state']=='settled'
    assert FakePayPal.captures==1
