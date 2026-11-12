"""Public boundary/config tests: no PayPal or model requests, real SQL labeled."""
from dataclasses import replace
import json
import os
from pathlib import Path
from unittest.mock import patch
import psycopg
import pytest
from fastapi.testclient import TestClient
from app import create_app
from settings import Settings, ConfigurationError
from public_demo import DemoAdmission, verify_reader
from prepare_deployment import prepare


def config_env():
    return {'QUERYVAULT_MODE':'public_demo','QUERYVAULT_PUBLIC_ORIGIN':'https://demo.example',
            'QUERYVAULT_DATASET':'synthetic-logistics-v1',
            'READER_DATABASE_URL':'postgresql://qv_reader:configuration-test-password@db:5432/queryvault'}


@pytest.fixture
def public_app():
    return create_app(Settings.from_env(config_env()))


@pytest.fixture
def public(public_app):
    return TestClient(public_app,base_url='https://demo.example')


@pytest.mark.parametrize('key,value',[
    ('QUERYVAULT_MODE','production'),('QUERYVAULT_PUBLIC_ORIGIN',''),
    ('QUERYVAULT_PUBLIC_ORIGIN','http://demo.example'),('QUERYVAULT_PUBLIC_ORIGIN','https://demo.example/'),
    ('QUERYVAULT_PUBLIC_ORIGIN','https://user:secret@demo.example'),('QUERYVAULT_PUBLIC_ORIGIN','https://demo.example?key=secret'),
    ('QUERYVAULT_PUBLIC_ORIGIN','https://demo.example:invalid'),('QUERYVAULT_PUBLIC_ORIGIN','https://*.example'),
    ('QUERYVAULT_DATASET','real-enterprise-data'),('READER_DATABASE_URL','not-a-database-url'),
    ('READER_DATABASE_URL','postgresql://postgres@db/queryvault'),
    ('LOCAL_API_KEY','operator-secret'),('DATABASE_URL','writer-secret'),
    ('PAYPAL_CLIENT_ID','provider-secret'),('PAYPAL_SECRET','provider-secret'),
    ('GROQ_API_KEY','provider-secret'),('MIGRATION_DB_PASSWORD_FILE','admin-secret-file'),
])
def test_public_configuration_fails_closed(key,value):
    env=config_env();env[key]=value
    with pytest.raises(ConfigurationError) as caught: Settings.from_env(env)
    assert 'configuration-test-password' not in str(caught.value)


def test_file_secret_and_conflicting_configuration(tmp_path):
    env=config_env();secret=tmp_path/'reader-url';secret.write_text(env.pop('READER_DATABASE_URL'))
    env['READER_DATABASE_URL_FILE']=str(secret)
    assert Settings.from_env(env).reader_url.startswith('postgresql:')
    env['READER_DATABASE_URL']='duplicate'
    with pytest.raises(ConfigurationError): Settings.from_env(env)
    env.pop('READER_DATABASE_URL');secret.unlink()
    with pytest.raises(ConfigurationError): Settings.from_env(env)


@pytest.mark.parametrize('method,path',[
    ('POST','/api/local-login'),('GET','/sessions'),('POST','/sessions'),
    ('GET','/sessions/private'),('POST','/sessions/private/authorize'),
    ('POST','/sessions/private/settle'),('POST','/sessions/private/reconcile'),
    ('POST','/sessions/private/recover-queries'),('GET','/sessions/private/ledger'),
    ('GET','/sessions/private/queries'),('GET','/sessions/private/agent-runs'),
    ('POST','/quote'),('POST','/execute'),('POST','/agent'),
    ('GET','/api/paypal/return-status?token=PRIVATE'),('GET','/paypal/return?token=PRIVATE'),
    ('GET','/paypal/cancel?token=PRIVATE'),
])
def test_public_requests_cannot_reach_operator_or_external_workflows(public,method,path):
    with patch('app.engine.payment_factory') as pay,patch('app.research') as model,patch('app.connect') as db:
        public.cookies.set('qv_local',os.environ['LOCAL_API_KEY'])
        r=public.request(method,path,headers={'X-API-Key':os.environ['LOCAL_API_KEY']},json={})
    assert r.status_code==403
    assert 'set-cookie' not in r.headers
    pay.assert_not_called();model.assert_not_called();db.assert_not_called()


@pytest.mark.parametrize('body',[
    {'sql':'SELECT * FROM shipments'}, {'template':'ports'},
    {'template':'shipment_count','sql':'SELECT pg_sleep(5)'},
    {'template':'shipment_count','session_id':'private'}, [], None,
])
def test_public_arbitrary_payloads_are_rejected_before_database(public,body):
    with patch('app.verify_reader') as verify,patch('app.read_query') as query:
        assert public.post('/demo/query',json=body).status_code==422
    verify.assert_not_called();query.assert_not_called()


def test_named_preview_runs_through_real_firewall_without_financial_authority(public):
    with patch('app.verify_reader'),patch('app.read_query',side_effect=[{'Total Cost':10},[{'shipment_count':600}]]) as query,patch('app.engine.payment_factory') as pay,patch('app.research') as model:
        r=public.post('/demo/query',json={'template':'shipment_count'})
    assert r.status_code==200 and r.json()['charged_cents']==0
    assert r.json()['rows']==[{'shipment_count':600}]
    assert '"vault_data"' in query.call_args.args[0]
    assert query.call_args.kwargs['reader_url'].startswith('postgresql:')
    pay.assert_not_called();model.assert_not_called()


def test_public_rate_and_concurrency_limits(public,public_app):
    public_app.state.admission=DemoAdmission(limit=1)
    with patch('app.verify_reader'),patch('app.read_query',side_effect=lambda *a,**kw: {'Total Cost':1} if kw.get('explain') else []):
        assert public.post('/demo/query',json={'template':'shipment_count'}).status_code==200
        r=public.post('/demo/query',json={'template':'shipment_count'})
        assert r.status_code==429 and r.headers['Retry-After']=='60'
        public_app.state.admission=DemoAdmission(concurrent=1)
        public_app.state.admission.slots.acquire()
        try: assert public.post('/demo/query',json={'template':'shipment_count'}).status_code==503
        finally: public_app.state.admission.slots.release()


def test_public_health_errors_and_configuration_are_safe(public):
    private='private-password database-account.sql'
    with patch('app.verify_reader',side_effect=psycopg.OperationalError(private)):
        assert public.get('/health/live').json()=={'status':'alive'}
        r=public.get('/health/ready');assert r.status_code==503
        assert private not in r.text
        assert public.get('/health').json()['paypal']=='disabled_in_public_demo'
        r=public.post('/demo/query',json={'template':'shipment_count'})
        assert r.status_code==503 and private not in r.text
    assert public.get('/api/config').json()['payments'] is False


def test_public_unknown_failures_do_not_log_secret_values(public,caplog):
    with patch('app.verify_reader',side_effect=RuntimeError('sensitive-password-must-not-log')):
        r=public.post('/demo/query',json={'template':'shipment_count'})
    assert r.status_code==500
    assert 'sensitive-password' not in r.text+caplog.text


def test_public_headers_origin_cookie_and_payload_boundary(public):
    r=public.post('/demo/query',headers={'Origin':'https://attacker.example'},json={'template':'shipment_count'})
    assert r.status_code==403 and 'Access-Control-Allow-Origin' not in r.headers
    assert r.headers['X-Frame-Options']=='DENY'
    assert "script-src 'self'" in r.headers['Content-Security-Policy']
    assert r.headers['Strict-Transport-Security']=='max-age=31536000'
    assert public.post('/demo/query',headers={'Sec-Fetch-Site':'cross-site'},json={}).status_code==403
    assert public.post('/demo/query',content='x'*16385).status_code==413
    assert public.get('/health/live',headers={'Host':'attacker.example'}).status_code==400
    assert 'set-cookie' not in public.get('/api/config').headers


def test_static_deep_links_do_not_hide_api_errors(public):
    assert public.get('/').status_code==200
    assert public.get('/buyer/research').status_code==200
    assert '<html' in public.get('/seller/ledger').text
    for path in ('/api/missing','/sessions/private/missing','/.env','/app.py','/.local/private-evidence/x.json','/assets/missing.js','/docs','/openapi.json'):
        r=public.get(path)
        assert r.status_code==404 and '<html' not in r.text,path


def test_public_history_is_sanitized_and_not_live(public):
    data=public.get('/demo/evidence').json()
    assert data['captured_cents']==105 and 'HISTORICAL' in data['label']
    assert 'authorization_id' not in json.dumps(data)
    summary=public.get('/evaluation').json()
    assert 'cases' not in summary and 'financial_test_evidence' not in summary
    assert 'Historical' in summary['label']


def test_local_bootstrap_and_operator_keys_cannot_be_used_from_remote_socket():
    c=TestClient(create_app(),base_url='http://127.0.0.1:8000',client=('203.0.113.55',1234))
    assert c.post('/api/local-login',headers={'Origin':'http://127.0.0.1:8000','X-Forwarded-For':'127.0.0.1'}).status_code==403
    assert c.get('/sessions',headers={'X-API-Key':os.environ['LOCAL_API_KEY']}).status_code==403


def test_production_lifespan_requires_assets_and_records_shutdown(public_app,tmp_path):
    with TestClient(public_app,base_url='https://demo.example') as client:
        assert not public_app.state.stopping
        assert client.get('/health/live').status_code==200
    assert public_app.state.stopping
    missing=create_app(replace(Settings.from_env(config_env()),frontend=tmp_path/'missing'))
    with pytest.raises(ConfigurationError):
        with TestClient(missing): pass


def test_public_mode_blocks_standalone_provider_clients(monkeypatch):
    from paypal_client import PayPalClient
    from agent import research
    monkeypatch.setenv('QUERYVAULT_MODE','public_demo')
    with pytest.raises(ValueError): PayPalClient()
    with pytest.raises(ValueError): research(None,'s','o','Never call a provider')


def test_compose_secrets_are_new_and_never_rotated(tmp_path):
    paths=prepare(tmp_path/'secrets')
    before={p.name:p.read_bytes() for p in paths}
    with pytest.raises(ValueError): prepare(tmp_path/'secrets')
    assert before=={p.name:p.read_bytes() for p in paths}


def test_container_frontend_build_includes_public_brand_assets():
    root=Path(__file__).parent
    dockerfile=(root/'Dockerfile').read_text(encoding='utf-8')
    dockerignore=(root/'.dockerignore').read_text(encoding='utf-8').splitlines()
    assert 'COPY frontend/public ./public' in dockerfile
    assert 'evaluation.json' not in dockerfile
    assert '!frontend/public/' in dockerignore
    assert '!frontend/public/**' in dockerignore
    assert '!evaluation.json' not in dockerignore
    assert '!sandbox-verification.json' not in dockerignore
    assert '!test-results.xml' not in dockerignore


def test_real_reader_has_no_financial_access_and_matches_exact_synthetic_data():
    verify_reader(os.environ['READER_DATABASE_URL'])
