from unittest.mock import patch
import json
import os
import pytest
import psycopg
from fastapi.testclient import TestClient
from app import app

def client(port=8000):
    return TestClient(app,base_url=f'http://127.0.0.1:{port}',headers={'X-API-Key':os.environ['LOCAL_API_KEY']})

def test_local_login_respects_actual_same_origin_port():
    c=client(8001)
    assert c.post('/api/local-login',headers={'Origin':'http://127.0.0.1:8001'}).status_code==200
    assert c.post('/api/local-login',headers={'Origin':'http://127.0.0.1:8000'}).status_code==403

@pytest.mark.parametrize('error,expected',[(psycopg.OperationalError('sensitive backend details'),503),(psycopg.errors.QueryCanceled('sensitive backend details'),504)])
def test_database_errors_are_safe_and_actionable(error,expected):
    with patch('app.engine.history',side_effect=error):
        result=client().get('/sessions/missing/queries')
    assert result.status_code==expected
    assert 'sensitive backend' not in result.text
    assert 'detail' in result.json()

def test_historical_evidence_is_labeled_and_not_a_payment_operation():
    with patch('app.engine.payment_factory') as payment:
        response=client().get('/demo/evidence')
    data=response.json()
    assert 'HISTORICAL' in data['label'] and 'not a live checkout' in data['label']
    assert data['authorized_cents']==2000 and data['captured_cents']==105
    assert data['ledger_difference_cents']==0
    assert 'authorization_id' not in json.dumps(data)
    payment.assert_not_called()

def test_frame_and_cache_controls():
    r=client().get('/health')
    assert r.headers['X-Frame-Options']=='DENY'
    assert r.headers['Cache-Control']=='no-store'

def test_untrusted_host_is_rejected():
    assert client().get('/health',headers={'Host':'attacker.example'}).status_code==400

def test_cross_site_writes_cannot_reach_financial_operations():
    with patch('app.engine.create') as create:
        assert client().post('/sessions',headers={'Origin':'https://attacker.example'}).status_code==403
        assert client().post('/sessions',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    create.assert_not_called()

def test_missing_environment_has_helpful_error(monkeypatch):
    c=client()
    monkeypatch.delenv('LOCAL_API_KEY',raising=False)
    r=c.post('/api/local-login',headers={'Origin':'http://127.0.0.1:8000'})
    assert r.status_code==503 and 'bootstrap.py' in r.json()['detail']
