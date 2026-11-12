import os
from unittest.mock import Mock,patch
import pytest
from fastapi.testclient import TestClient
from app import app
from engine import Engine
from test_engine import FakePayPal

@pytest.mark.parametrize('path',['/paypal/return','/paypal/cancel'])
def test_return_landing_is_available_without_cookie_and_never_mutates(path):
    client=TestClient(app,base_url='http://127.0.0.1:8000')
    with patch('app.engine.payment_factory') as pay:
        result=client.get(path+'?token=ORDER1&PayerID=untrusted')
    assert result.status_code==200
    assert 'Returning from PayPal does not prove approval' in result.text
    assert '/api/paypal/return-status?token=' in result.text
    assert "fetch('/sessions" not in result.text
    assert 'authorize(' not in result.text and 'capture(' not in result.text
    pay.assert_not_called()

@pytest.mark.parametrize('status,auth_status',[('CREATED',None),('APPROVED',None),('COMPLETED','VOIDED')])
def test_status_is_verified_independently_not_trusted_from_callback(status,auth_status):
    e=Engine(FakePayPal)
    owner='test-return-'+status
    record=e.create(owner)
    provider=Mock()
    provider.__enter__=Mock(return_value=provider)
    provider.__exit__=Mock(return_value=None)
    provider.get_order.return_value={'id':record['order_id'],'status':status,'purchase_units':[{'payments':{'authorizations':[{'id':'AUTH1','status':'CREATED'}] if auth_status else []}}]}
    provider.get_authorization.return_value={'id':'AUTH1','status':auth_status,'amount':{'value':'20.00','currency_code':'USD'}}
    e.payment_factory=Mock(return_value=provider)
    c=TestClient(app,base_url='http://127.0.0.1:8000',headers={'X-API-Key':os.environ['LOCAL_API_KEY']})
    with patch('app.engine',e),patch('app.OWNER',owner):
        r=c.get('/api/paypal/return-status?token=ORDER1&approved=true&PayerID=ignored')
        assert r.status_code==200
        assert r.json()['buyer_approval_verified']==(status=='APPROVED')
        if auth_status:
            assert r.json()['authorizations'][0]['status']=='VOIDED'
            provider.get_authorization.assert_called_once_with('AUTH1')
        assert c.get('/api/paypal/return-status?token=UNKNOWN').status_code==404
        assert c.get('/api/paypal/return-status?token=../bad').status_code==422
    provider.authorize_order.assert_not_called()
    provider.capture_session_funds.assert_not_called()
    provider.void_session.assert_not_called()

def test_status_endpoint_requires_workspace_access():
    c=TestClient(app,base_url='http://127.0.0.1:8000')
    assert c.get('/api/paypal/return-status?token=ORDER1').status_code==401
