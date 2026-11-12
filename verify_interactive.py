"""Isolated Phase B2 verification; real, non-billing providers are opt-in.

This script makes a fresh synthetic-only PostgreSQL cluster/database, runs the
real migration and production entrypoint, exercises the actual HTTP workflow,
and stops only the services it created. It never calls PayPal.
"""
import json
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

import psycopg
import requests
from dotenv import dotenv_values

from demo_quota import DemoQuotaStore
from public_demo import verify_reader
from setup_local import executable


ROOT = Path(__file__).resolve().parent


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def write_secret(path: Path, value: str):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as target:
        target.write(value)
        target.write('\n')


def main():
    parser=argparse.ArgumentParser()
    provider_group=parser.add_mutually_exclusive_group()
    provider_group.add_argument('--no-live',action='store_true',help='disable AI and run only the real fixed-query fallback')
    provider_group.add_argument('--mock-provider',action='store_true',help='inject deterministic test proposals into the real B2 HTTP service; never contacts Groq')
    parser.add_argument('--browser-qa',action='store_true',help='keep the isolated service alive briefly for manual browser inspection; use with --no-live or --mock-provider')
    parser.add_argument('--report-file',type=Path,help='write results to a new report path instead of replacing a saved verification report')
    args=parser.parse_args()
    if args.report_file:
        proposed_report_path = args.report_file if args.report_file.is_absolute() else ROOT / args.report_file
        if proposed_report_path.exists():
            parser.error('--report-file must name a new file; existing verification evidence is never overwritten')
    check_id = uuid.uuid4().hex[:12]
    target = ROOT / '.local' / ('interactive-deployment-check-' + check_id)
    target.mkdir(parents=True, exist_ok=False)
    scratch = Path(tempfile.mkdtemp(prefix='qv-phase-b2-')).resolve()
    pgdata = target / 'pgdata'
    pg_port = free_port()
    web_port = free_port()
    admin_password = secrets.token_urlsafe(40)
    reader_password = secrets.token_urlsafe(40)
    origin = f'http://127.0.0.1:{web_port}'
    reader_dsn = f'postgresql://qv_interactive_reader:{reader_password}@127.0.0.1:{pg_port}/queryvault_interactive_demo'
    admin_dsn = f'postgresql://postgres:{admin_password}@127.0.0.1:{pg_port}/queryvault_interactive_demo'
    if args.mock_provider:
        provider_key = 'deterministic-mock-provider-key-not-a-secret'
    elif args.no_live or args.browser_qa:
        provider_key = ''
    else:
        env_file = dotenv_values(ROOT / '.env') if (ROOT / '.env').is_file() else {}
        provider_key = os.environ.get('GROQ_API_KEY') or env_file.get('GROQ_API_KEY') or ''
    reader_file = scratch / 'reader-dsn'
    provider_file = scratch / 'groq-key'
    reader_password_file = scratch / 'reader-password'
    quota_path = scratch / 'quota.sqlite3'
    mock_calls_file = target / 'mock-provider-calls.log'
    write_secret(reader_file, reader_dsn)
    write_secret(reader_password_file, reader_password)
    if provider_key:
        write_secret(provider_file, str(provider_key))
    else:
        write_secret(provider_file, '')
    clean_env = {k: v for k, v in os.environ.items()
                 if not k.startswith(('QUERYVAULT_', 'PAYPAL_', 'GROQ_', 'DB_', 'MIGRATION_', 'READER_', 'PG'))
                 and k not in ('DATABASE_URL', 'DATABASE_URL_FILE', 'LOCAL_API_KEY', 'PORT')}
    clean_env.update(QUERYVAULT_MODE='public_interactive', QUERYVAULT_PUBLIC_ORIGIN=origin,
                     QUERYVAULT_DATASET='synthetic-logistics-v1',
                     QUERYVAULT_QUOTA_DB_PATH=str(quota_path),
                     QUERYVAULT_INTERACTIVE_ENABLED='true' if provider_key else 'false',
                     READER_DATABASE_URL_FILE=str(reader_file), GROQ_API_KEY_FILE=str(provider_file),
                     QUERYVAULT_HOST='127.0.0.1', PORT=str(web_port))
    if args.mock_provider:
        clean_env['QV_TEST_MOCK_PROVIDER_CALLS_FILE'] = str(mock_calls_file)
    admin = {'host': '127.0.0.1', 'port': pg_port, 'user': 'postgres', 'password': admin_password,
             'dbname': 'queryvault_interactive_demo', 'connect_timeout': 5}
    process = None
    pg_started = False
    log = None
    saved_plan_id = None
    expected_available_cents = 300
    report = {
        'mode': 'isolated public_interactive production-entrypoint verification',
        'provider': ('deterministic mocked proposal; no external provider connection' if args.mock_provider else
                     'not configured; real fixed-query fallback only' if not provider_key else
                     'real Groq, one request maximum'),
        'live_ai_calls': 0,
        'paypal_calls': 0,
        'financial_tables_created': False,
        'checks': {},
    }

    def mock_provider_call_count():
        return len(mock_calls_file.read_text(encoding='ascii').splitlines()) if mock_calls_file.exists() else 0

    def pg(action):
        subprocess.run([executable('pg_ctl'), '-D', str(pgdata), '-l', str(target / 'postgres.log'), '-w', action],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=30)

    def start_web():
        nonlocal process, log
        log = (target / 'web.log').open('a', encoding='utf-8')
        if args.mock_provider:
            mock_entrypoint = '''
import os
from pathlib import Path
import interactive_api
from public_agent import PlannerError

def deterministic_propose(objective, *, api_key, model):
    with Path(os.environ["QV_TEST_MOCK_PROVIDER_CALLS_FILE"]).open("a", encoding="ascii") as calls:
        calls.write("call\\n")
    question = objective.casefold()
    if "concurrency probe" in question:
        import time
        time.sleep(0.75)
    if "provider unavailable" in question:
        raise PlannerError("The research provider is unavailable. No query was executed.")
    if "unsupported" in question:
        return {"supported": False, "scope_changed": False, "sql": "", "reason": "The test proposal is unsupported.", "tokens_used": 32}
    if "scope change" in question:
        return {"supported": True, "scope_changed": True, "sql": "", "reason": "The test proposal changes scope.", "tokens_used": 32}
    sql = "SELECT COUNT(*) AS shipment_count FROM vault_data.shipments WHERE shipped_on >= DATE '2026-10-01' AND shipped_on < DATE '2026-11-01'"
    if "unsafe sql" in question:
        sql = "SELECT current_user"
    return {"supported": True, "scope_changed": False, "sql": sql,
            "reason": "Deterministic test proposal; no live AI inference was used.", "tokens_used": 32}

interactive_api.propose = deterministic_propose
from serve import main
raise SystemExit(main())
'''
            command = [sys.executable, '-c', mock_entrypoint]
        else:
            command = [sys.executable, 'serve.py']
        process = subprocess.Popen(command, cwd=ROOT, env=clean_env,
                                   stdout=log, stderr=log)
        for _ in range(150):
            if process.poll() is not None:
                raise RuntimeError('Production entrypoint exited before readiness')
            try:
                response = requests.get(origin + '/health/ready', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=1)
                if response.status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(.2)
        raise RuntimeError('Production entrypoint readiness timed out')

    def stop_web():
        nonlocal process, log
        if process is not None:
            process.terminate()
            process.wait(timeout=20)
            process = None
        if log is not None:
            log.close()
            log = None

    try:
        pw = target / 'init-password'
        write_secret(pw, admin_password)
        try:
            subprocess.run([executable('initdb'), '-D', str(pgdata), '-U', 'postgres', '-A', 'scram-sha-256',
                            '--pwfile', str(pw), '--encoding=UTF8', '--locale=C'],
                           check=True, capture_output=True, timeout=60)
        finally:
            pw.unlink(missing_ok=True)
        with (pgdata / 'postgresql.conf').open('a', encoding='utf-8') as config:
            config.write(f"\nlisten_addresses='127.0.0.1'\nport={pg_port}\nmax_connections=32\n")
        pg('start')
        pg_started = True
        admin_cluster = {k: v for k, v in admin.items() if k != 'dbname'}
        with psycopg.connect(**admin_cluster, autocommit=True) as conn:
            conn.execute('CREATE DATABASE queryvault_interactive_demo')
        migration_env = clean_env | {
            'MIGRATION_DATABASE_URL': admin_dsn,
            'READER_DB_PASSWORD_FILE': str(reader_password_file),
        }
        for _ in range(2):
            subprocess.run([sys.executable, 'migrate_deployment.py'], cwd=ROOT, env=migration_env,
                           check=True, capture_output=True, timeout=60)
        report['checks']['dedicated_synthetic_migration_and_repeatability'] = True
        try:
            verify_reader(reader_dsn,expected_database='queryvault_interactive_demo',expected_role='qv_interactive_reader')
        except Exception as exc:
            report['reader_verification_failure_type']=type(exc).__name__
            raise
        report['checks']['restricted_interactive_reader_fixture_and_grants'] = True
        with psycopg.connect(**admin) as conn:
            tables = conn.execute("SELECT table_schema,table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1,2").fetchall()
            report['checks']['no_commercial_or_financial_tables'] = tables == [('vault_data','ports'),('vault_data','routes'),('vault_data','shipments')]
            assert report['checks']['no_commercial_or_financial_tables'], tables
            reference = conn.execute("SELECT COUNT(*) FROM vault_data.shipments WHERE shipped_on >= DATE '2026-10-01' AND shipped_on < DATE '2026-11-01'").fetchone()[0]
            assert reference == 600
        report['independent_october_reference_count'] = reference
        backup_file = target / 'synthetic-postgres-backup.dump'
        restore_database = 'queryvault_interactive_restore'
        pg_tools_env = clean_env | {'PGPASSWORD': admin_password}
        subprocess.run([executable('pg_dump'), '--format=custom', '--no-owner', '--no-acl',
                        '--host=127.0.0.1', f'--port={pg_port}', '--username=postgres',
                        f'--dbname={admin["dbname"]}', f'--file={backup_file}'],
                       env=pg_tools_env, check=True, capture_output=True, timeout=60)
        with psycopg.connect(**admin_cluster, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE {restore_database}')
        subprocess.run([executable('pg_restore'), '--no-owner', '--no-acl', '--exit-on-error',
                        '--host=127.0.0.1', f'--port={pg_port}', '--username=postgres',
                        f'--dbname={restore_database}', str(backup_file)],
                       env=pg_tools_env, check=True, capture_output=True, timeout=60)
        with psycopg.connect(**(admin | {'dbname': restore_database})) as conn:
            restored_reference = conn.execute("SELECT COUNT(*) FROM vault_data.shipments WHERE shipped_on >= DATE '2026-10-01' AND shipped_on < DATE '2026-11-01'").fetchone()[0]
        with psycopg.connect(**admin_cluster, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE {restore_database}')
        report['checks']['synthetic_postgres_backup_restores_reference_data'] = restored_reference == reference == 600
        quota_store=DemoQuotaStore(quota_path)
        quota_store.initialize()
        quota_store.validate()
        report['checks']['persistent_quota_volume_initialized_explicitly'] = True
        check = subprocess.run([sys.executable, 'serve.py', '--check'], cwd=ROOT, env=clean_env,
                               capture_output=True, timeout=30)
        report['checks']['production_mode_configuration'] = check.returncode == 0
        assert check.returncode == 0
        start_web()
        with requests.Session() as client:
            home = client.get(origin + '/', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            report['checks']['guest_homepage_and_latest_static_build'] = (
                home.status_code == 200 and 'QueryVault' in home.text and 'assets/index-' in home.text)
            favicon = client.get(origin + '/favicon.svg', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            report['checks']['current_favicon_served'] = favicon.status_code == 200 and 'image/svg+xml' in favicon.headers.get('content-type', '')
            manifest = client.get(origin + '/site.webmanifest', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            brand = client.get(origin + '/brand/queryvault-horizontal-dark.svg', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            report['checks']['current_manifest_and_brand_assets_served'] = (
                manifest.status_code == 200 and 'manifest+json' in manifest.headers.get('content-type', '') and
                brand.status_code == 200 and 'image/svg+xml' in brand.headers.get('content-type', ''))
            deep_link = client.get(origin + '/research', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            report['checks']['guest_deep_link_and_refresh_return_application'] = deep_link.status_code == 200 and '<html' in deep_link.text
            assert all(report['checks'][name] for name in (
                'guest_homepage_and_latest_static_build', 'current_favicon_served',
                'current_manifest_and_brand_assets_served', 'guest_deep_link_and_refresh_return_application'))
            response = client.get(origin + '/api/config', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            response.raise_for_status()
            cfg = response.json()
            report['checks']['public_capability_and_payment_boundaries'] = (
                cfg['mode'] == 'public_interactive' and cfg['operator_workflows'] is False and
                cfg['payments'] is False and cfg['live_ai'] is False and
                cfg['interactive_ai'] is bool(provider_key))
            assert report['checks']['public_capability_and_payment_boundaries']
            health = client.get(origin + '/health', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            health.raise_for_status()
            report['checks']['readiness_and_database_access'] = health.json()['database'] == 'connected'
            assert report['checks']['readiness_and_database_access']
            state = client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            state.raise_for_status()
            assert state.json()['enabled'] is bool(provider_key)
            report['checks']['persistent_virtual_allowance_and_feature_flag'] = state.json()['available_cents'] == 300
            assert report['checks']['persistent_virtual_allowance_and_feature_flag']
            expected_available_cents=state.json()['available_cents']
            if provider_key:
                if args.mock_provider:
                    report['mocked_provider_calls'] = 0
                else:
                    report['live_ai_calls'] = 1
                payload = {'objective': 'How many shipments occurred in October 2026?', 'request_id': str(uuid.uuid4())}
                plan_response = client.post(origin + '/interactive/plan', headers={'Origin': origin, 'Host': f'127.0.0.1:{web_port}'}, json=payload, timeout=25)
                if plan_response.status_code == 200:
                    plan = plan_response.json()
                    saved_plan_id=plan.get('plan_id')
                    workflow_key = 'mocked_workflow' if args.mock_provider else 'live_ai'
                    report[workflow_key] = {
                        'state': plan.get('state'),
                        'model_tokens_used': plan.get('model_tokens_used'),
                        'firewall': plan.get('firewall'),
                        'price_cents': plan.get('quote', {}).get('price_cents') if plan.get('quote') else None,
                        'budget_decision': plan.get('quote', {}).get('budget_decision') if plan.get('quote') else None,
                    }
                    report['checks']['mocked_proposal_real_firewall_and_database_plan' if args.mock_provider else 'one_bounded_real_groq_proposal'] = True
                    if plan.get('state') == 'quote_ready' and plan.get('quote', {}).get('budget_decision') == 'affordable':
                        if args.mock_provider:
                            request_headers = {'Origin': origin, 'Host': f'127.0.0.1:{web_port}'}
                            repeated_plan = client.post(origin + '/interactive/plan', headers=request_headers, json=payload, timeout=10)
                            report['checks']['idempotent_proposal_request_reuses_plan'] = repeated_plan.status_code == 200 and repeated_plan.json().get('plan_id') == saved_plan_id
                            report['checks']['duplicate_proposal_does_not_call_provider_twice'] = mock_provider_call_count() == 1
                            sql = plan.get('technical', {}).get('sql', '')
                            expected_hash = hashlib.sha256(sql.encode('utf-8')).hexdigest()
                            report['checks']['quote_hash_binds_exact_canonical_sql'] = expected_hash == plan['quote']['sql_hash']
                            not_accepted = client.post(origin + '/interactive/execute', headers=request_headers, json={'plan_id': saved_plan_id}, timeout=8)
                            report['checks']['execution_requires_explicit_acceptance'] = not_accepted.status_code == 409
                            raw_sql = client.post(origin + '/interactive/execute', headers=request_headers,
                                                  json={'plan_id': saved_plan_id, 'sql': 'SELECT 1'}, timeout=8)
                            report['checks']['execution_endpoint_rejects_client_sql'] = raw_sql.status_code == 422
                            wrong_hash = client.post(origin + '/interactive/accept', headers=request_headers,
                                                     json={'plan_id': saved_plan_id, 'sql_hash': '0' * 64,
                                                           'accepted_price_cents': plan['quote']['accepted_ceiling_cents']}, timeout=8)
                            wrong_price = client.post(origin + '/interactive/accept', headers=request_headers,
                                                      json={'plan_id': saved_plan_id, 'sql_hash': plan['quote']['sql_hash'],
                                                            'accepted_price_cents': plan['quote']['accepted_ceiling_cents'] + 1}, timeout=8)
                            report['checks']['changed_quote_hash_and_price_are_rejected'] = wrong_hash.status_code == 409 and wrong_price.status_code == 409
                            accepted = client.post(origin + '/interactive/accept', headers=request_headers,
                                                   json={'plan_id': saved_plan_id, 'sql_hash': plan['quote']['sql_hash'],
                                                         'accepted_price_cents': plan['quote']['accepted_ceiling_cents']}, timeout=8)
                            accepted.raise_for_status()
                            repeated_accept = client.post(origin + '/interactive/accept', headers=request_headers,
                                                          json={'plan_id': saved_plan_id, 'sql_hash': plan['quote']['sql_hash'],
                                                                'accepted_price_cents': plan['quote']['accepted_ceiling_cents']}, timeout=8)
                            wallet_reserved = client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5).json()
                            report['checks']['acceptance_is_idempotent_and_reserves_exact_quote'] = (
                                accepted.status_code == 200 and repeated_accept.status_code == 200 and
                                repeated_accept.json().get('state') == 'accepted' and
                                wallet_reserved['reserved_cents'] == plan['quote']['price_cents'])
                            executed = client.post(origin + '/interactive/execute', headers=request_headers,
                                                   json={'plan_id': saved_plan_id}, timeout=15)
                            executed.raise_for_status()
                            data = executed.json()
                            rows = data.get('result', {}).get('rows', [])
                            values = [int(v) for row in rows for v in row.values() if str(v).isdigit()]
                            repeated_execution = client.post(origin + '/interactive/execute', headers=request_headers,
                                                             json={'plan_id': saved_plan_id}, timeout=15)
                            repeated_execution.raise_for_status()
                            final_wallet = client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5).json()
                            expected_available_cents = final_wallet['available_cents']
                            quota_backup = scratch / 'quota-restored.sqlite3'
                            with sqlite3.connect(quota_path) as source_quota, sqlite3.connect(quota_backup) as backup_quota:
                                source_quota.backup(backup_quota)
                            DemoQuotaStore(quota_backup).validate()
                            with sqlite3.connect(quota_backup) as backup_quota:
                                restored_wallet = backup_quota.execute(
                                    'SELECT allowance_cents,spent_cents,reserved_cents FROM visitors WHERE visitor_hash=?',
                                    (hashlib.sha256(client.cookies.get('qv_demo_visitor').encode('utf-8')).hexdigest(),)
                                ).fetchone()
                            report['checks']['isolated_quota_backup_restores_exact_virtual_wallet'] = (
                                restored_wallet == (300, plan['quote']['price_cents'], 0))
                            report[workflow_key].update({'execution_state': data.get('state'), 'result_rows': rows,
                                                         'virtual_charge_cents': data.get('result', {}).get('charged_cents'),
                                                         'independent_reference_match': reference in values})
                            report['checks']['accepted_read_only_result_matches_independent_count'] = data.get('state') == 'completed' and reference in values
                            report['checks']['duplicate_execution_replays_without_double_spend'] = (
                                repeated_execution.json().get('result') == data.get('result') and
                                final_wallet['spent_cents'] == plan['quote']['price_cents'] and
                                final_wallet['reserved_cents'] == 0)
                            status = client.get(origin + '/interactive/plans/' + saved_plan_id,
                                                headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
                            report['checks']['completed_result_is_available_to_same_visitor'] = status.status_code == 200 and status.json().get('state') == 'completed'
                            report['mocked_provider_calls'] = mock_provider_call_count() if args.mock_provider else 0
                            calls_before_scenarios = mock_provider_call_count()

                            # Refusal, malformed-input and provider-failure cases use
                            # separate synthetic visitors and never call an external provider.
                            raw_sql_client = requests.Session()
                            raw_sql_client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
                            raw_sql_response = raw_sql_client.post(
                                origin + '/interactive/plan', headers=request_headers,
                                json={'objective': 'SELECT * FROM shipments', 'request_id': str(uuid.uuid4())}, timeout=8)
                            report['checks']['raw_sql_objective_refused_before_provider'] = raw_sql_response.status_code == 422 and mock_provider_call_count() == calls_before_scenarios

                            def plan_scenario(objective):
                                scenario = requests.Session()
                                scenario.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
                                response = scenario.post(
                                    origin + '/interactive/plan', headers=request_headers,
                                    json={'objective': objective, 'request_id': str(uuid.uuid4())}, timeout=15)
                                return scenario, response

                            _unsafe_client, unsafe_response = plan_scenario('Propose unsafe SQL for shipments')
                            unsafe = unsafe_response.json()
                            report['checks']['firewall_refusal_has_no_quote_or_result'] = (
                                unsafe_response.status_code == 200 and unsafe.get('state') == 'sql_rejected' and
                                unsafe.get('firewall') == 'rejected' and unsafe.get('quote') is None and
                                unsafe.get('technical') is None and 'result' not in unsafe)
                            _unsupported_client, unsupported_response = plan_scenario('Unsupported question about shipments')
                            unsupported = unsupported_response.json()
                            report['checks']['unsupported_request_is_an_honest_refusal'] = (
                                unsupported_response.status_code == 200 and unsupported.get('state') == 'refused' and
                                unsupported.get('quote') is None and 'result' not in unsupported)
                            _scope_client, scope_response = plan_scenario('Request a scope change for shipments')
                            scope = scope_response.json()
                            report['checks']['scope_change_stops_before_quote'] = (
                                scope_response.status_code == 200 and scope.get('state') == 'scope_review' and
                                scope.get('quote') is None and 'result' not in scope)
                            _provider_client, provider_response = plan_scenario('Provider unavailable for shipments')
                            provider_error = provider_response.json().get('detail', {})
                            report['checks']['provider_failure_is_generic_and_executes_nothing'] = (
                                provider_response.status_code == 503 and provider_error.get('code') == 'provider_unavailable' and
                                provider_error.get('message') == 'The research provider is unavailable. No query was executed.' and
                                'result' not in provider_error)

                            malformed = client.post(origin + '/interactive/plan', headers=request_headers,
                                                    json={'objective': 'x', 'request_id': 'not-a-uuid'}, timeout=8)
                            report['checks']['malformed_input_refused'] = malformed.status_code == 422
                            wrong_origin = client.post(origin + '/interactive/plan', headers={'Origin': 'http://attacker.invalid'},
                                                       json={'objective': 'Question about shipments', 'request_id': str(uuid.uuid4())}, timeout=8)
                            report['checks']['cross_origin_plan_refused'] = wrong_origin.status_code == 403
                            oversized = client.post(origin + '/interactive/plan', headers=request_headers, data='x' * 17000, timeout=8)
                            report['checks']['oversized_request_refused'] = oversized.status_code == 413
                            bad_host = client.get(origin + '/health/live', headers={'Host': 'attacker.invalid'}, timeout=8)
                            report['checks']['untrusted_host_refused'] = bad_host.status_code == 400

                            isolation_cases = [
                                ('POST', '/api/local-login'), ('GET', '/sessions'), ('POST', '/sessions'),
                                ('GET', '/sessions/synthetic-private/ledger'), ('GET', '/sessions/synthetic-private/queries'),
                                ('POST', '/sessions/synthetic-private/authorize'), ('POST', '/sessions/synthetic-private/settle'),
                                ('POST', '/sessions/synthetic-private/reconcile'), ('POST', '/sessions/synthetic-private/recover-queries'),
                                ('POST', '/quote'), ('POST', '/execute'), ('POST', '/agent'),
                                ('POST', '/paypal/create-order'), ('POST', '/paypal/capture'), ('POST', '/paypal/void'),
                            ]
                            isolation_results = []
                            isolation_statuses = {}
                            local_key_sentinel = 'synthetic-local-operator-key-not-a-credential'
                            client.cookies.set('qv_local', local_key_sentinel)
                            for method, path in isolation_cases:
                                blocked = client.request(method, origin + path,
                                                         headers={'Origin': origin, 'Host': f'127.0.0.1:{web_port}',
                                                                  'X-API-Key': local_key_sentinel}, json={}, timeout=8)
                                isolation_statuses[f'{method} {path}'] = blocked.status_code
                                isolation_results.append(blocked.status_code in (403, 404, 405))
                            report['operator_payment_route_statuses'] = isolation_statuses
                            report['checks']['local_operator_payment_and_seller_routes_are_blocked_with_cookie_and_key'] = all(isolation_results)
                            private_paths = [
                                '/.env', '/.local/private-evidence/test.json', '/app.py',
                                '/docs', '/openapi.json', '/paypal-reconciliation-audit.json',
                            ]
                            private_results = [client.get(origin + path, headers={'Host': f'127.0.0.1:{web_port}'}, timeout=8).status_code == 404
                                               for path in private_paths]
                            report['checks']['private_files_and_operator_api_docs_are_not_served'] = all(private_results)
                            config_text = json.dumps(cfg)
                            report['checks']['provider_key_not_exposed_in_public_configuration'] = 'deterministic-mock-provider-key' not in config_text

                            # Exercise a low virtual balance by changing only this
                            # disposable verification database, never the app defaults.
                            low_wallet_client = requests.Session()
                            low_wallet_client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
                            visitor_token = low_wallet_client.cookies.get('qv_demo_visitor')
                            visitor_hash = hashlib.sha256(visitor_token.encode('utf-8')).hexdigest()
                            with sqlite3.connect(quota_path) as quota_conn:
                                quota_conn.execute('UPDATE visitors SET allowance_cents=0 WHERE visitor_hash=?', (visitor_hash,))
                            low_wallet = low_wallet_client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5).json()
                            low_wallet_plan = low_wallet_client.post(
                                origin + '/interactive/plan', headers=request_headers,
                                json={'objective': 'How many shipments occurred in October 2026?', 'request_id': str(uuid.uuid4())}, timeout=15)
                            low_wallet_data = low_wallet_plan.json()
                            low_wallet_after = low_wallet_client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5).json()
                            report['checks']['insufficient_allowance_is_distinct_and_not_spent'] = (
                                low_wallet['available_cents'] == 0 and low_wallet_plan.status_code == 200 and
                                low_wallet_data.get('state') == 'over_budget' and low_wallet_data.get('quote', {}).get('budget_decision') == 'over_budget' and
                                'result' not in low_wallet_data and low_wallet_after['spent_cents'] == 0 and low_wallet_after['reserved_cents'] == 0)

                            before_concurrency_calls = mock_provider_call_count()
                            concurrent_clients = []
                            for index in range(3):
                                concurrent_client = requests.Session()
                                concurrent_client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
                                concurrent_clients.append(concurrent_client)
                            def concurrency_probe(index):
                                return concurrent_clients[index].post(
                                    origin + '/interactive/plan', headers=request_headers,
                                    json={'objective': f'Concurrency probe shipment group {index}', 'request_id': str(uuid.uuid4())}, timeout=20)
                            with ThreadPoolExecutor(max_workers=3) as pool:
                                concurrent_responses = list(pool.map(concurrency_probe, range(3)))
                            concurrent_codes = sorted(response.status_code for response in concurrent_responses)
                            report['checks']['model_concurrency_never_exceeds_two'] = (
                                concurrent_codes.count(200) == 2 and concurrent_codes.count(503) == 1 and
                                any(response.status_code == 503 and response.json().get('detail', {}).get('code') == 'model_busy'
                                    for response in concurrent_responses) and
                                mock_provider_call_count() - before_concurrency_calls == 2)

                            before_exhaustion_calls = mock_provider_call_count()
                            with sqlite3.connect(quota_path) as quota_conn:
                                quota_conn.execute("UPDATE meta SET value='120' WHERE key='lifetime_ai_calls'")
                            exhausted_client = requests.Session()
                            exhausted_client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
                            exhausted_response = exhausted_client.post(
                                origin + '/interactive/plan', headers=request_headers,
                                json={'objective': 'Question about shipment routes', 'request_id': str(uuid.uuid4())}, timeout=8)
                            report['checks']['lifetime_quota_exhaustion_fails_closed'] = (
                                exhausted_response.status_code == 429 and mock_provider_call_count() == before_exhaustion_calls)
                            report['mocked_provider_calls'] = mock_provider_call_count()

                            marker = quota_path.parent / 'AI_DISABLED'
                            marker.write_text('disabled by isolated verification', encoding='ascii')
                            disabled_state = client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
                            disabled_plan = client.post(origin + '/interactive/plan', headers=request_headers,
                                                        json={'objective': 'Question about shipment routes', 'request_id': str(uuid.uuid4())}, timeout=8)
                            disabled_fallback = client.post(origin + '/demo/query', headers=request_headers,
                                                            json={'template': 'shipment_count'}, timeout=8)
                            report['checks']['kill_switch_disables_ai_but_preserves_free_read_only_demo'] = (
                                disabled_state.status_code == 200 and disabled_state.json()['enabled'] is False and
                                disabled_plan.status_code == 503 and disabled_plan.json().get('detail', {}).get('code') == 'ai_disabled' and
                                disabled_fallback.status_code == 200 and disabled_fallback.json().get('rows') == [{'shipment_count': 600}])
                            marker.unlink(missing_ok=True)
                        else:
                            accepted = client.post(origin + '/interactive/accept', headers={'Origin': origin, 'Host': f'127.0.0.1:{web_port}'},
                                                   json={'plan_id': plan['plan_id'], 'sql_hash': plan['quote']['sql_hash'],
                                                         'accepted_price_cents': plan['quote']['accepted_ceiling_cents']}, timeout=8)
                            accepted.raise_for_status()
                            executed = client.post(origin + '/interactive/execute', headers={'Origin': origin, 'Host': f'127.0.0.1:{web_port}'},
                                                   json={'plan_id': plan['plan_id']}, timeout=15)
                            executed.raise_for_status()
                            data = executed.json()
                            expected_available_cents=data.get('allowance',{}).get('available_cents',expected_available_cents)
                            rows = data.get('result', {}).get('rows', [])
                            values = [int(v) for row in rows for v in row.values() if str(v).isdigit()]
                            report[workflow_key].update({'execution_state': data.get('state'), 'result_rows': rows,
                                                         'virtual_charge_cents': data.get('result', {}).get('charged_cents'),
                                                         'independent_reference_match': reference in values})
                            report['checks']['accepted_read_only_result_matches_independent_count'] = data.get('state') == 'completed' and reference in values
                    else:
                        report['checks']['non_executable_refusal_or_unaffordable_quote'] = plan.get('state') in ('refused','scope_review','sql_rejected','over_budget')
                else:
                    report['mocked_workflow' if args.mock_provider else 'live_ai'] = {
                        'state': 'provider_unavailable', 'http_status': plan_response.status_code,
                        'message': plan_response.json().get('detail', {}).get('message', 'Provider unavailable')}
                    report['checks']['mocked_proposal_real_firewall_and_database_plan' if args.mock_provider else 'one_bounded_real_groq_proposal'] = False
                report['checks']['no_paypal_endpoint'] = client.post(origin + '/sessions', headers={'Origin': origin}, json={}, timeout=5).status_code == 403
                assert report['checks']['no_paypal_endpoint']
            else:
                preview = client.post(origin + '/demo/query', headers={'Origin': origin}, json={'template': 'shipment_count'}, timeout=10)
                preview.raise_for_status()
                report['checks']['disabled_ai_keeps_fixed_read_only_fallback'] = preview.json()['rows'] == [{'shipment_count':600}]
                assert report['checks']['disabled_ai_keeps_fixed_read_only_fallback']
            pg('stop')
            pg_started = False
            database_unavailable_status = None
            database_unavailable_error = None
            liveness_during_outage = None
            try:
                liveness_during_outage = requests.get(
                    origin + '/health/live', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5).status_code
            except requests.RequestException as exc:
                liveness_during_outage = type(exc).__name__
            try:
                unavailable = requests.get(origin + '/health/ready', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=15)
                database_unavailable_status = unavailable.status_code
                database_unavailable = unavailable.status_code == 503
            except requests.RequestException as exc:
                database_unavailable = False
                database_unavailable_error = type(exc).__name__
            pg('start')
            pg_started = True
            recovered = False
            database_recovery_status = None
            for _ in range(30):
                try:
                    ready = requests.get(origin + '/health/ready', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=2)
                    database_recovery_status = ready.status_code
                    if ready.status_code == 200:
                        recovered = True
                        break
                except requests.RequestException:
                    pass
                time.sleep(.2)
            report['database_outage_readiness_status'] = database_unavailable_status
            report['database_outage_readiness_error'] = database_unavailable_error
            report['database_outage_liveness_status'] = liveness_during_outage
            report['database_recovery_readiness_status'] = database_recovery_status
            report['checks']['database_outage_fails_readiness_and_recovers_without_web_restart'] = database_unavailable and recovered
            stop_web()
            start_web()
            state2 = client.get(origin + '/interactive/state', headers={'Host': f'127.0.0.1:{web_port}'}, timeout=5)
            state2.raise_for_status()
            report['checks']['quota_and_visitor_state_survive_web_restart'] = state2.json()['available_cents'] == expected_available_cents
            assert report['checks']['quota_and_visitor_state_survive_web_restart']
            if saved_plan_id:
                saved=client.get(origin+'/interactive/plans/'+saved_plan_id,headers={'Host':f'127.0.0.1:{web_port}'},timeout=5)
                saved.raise_for_status()
                report['checks']['visitor_plan_and_result_survive_web_restart']=saved.json().get('plan_id')==saved_plan_id
                assert report['checks']['visitor_plan_and_result_survive_web_restart']
        report['passed'] = all(report['checks'].values())
        if args.browser_qa:
            report['browser_qa_url']=origin
            print(json.dumps({'browser_qa_url':origin,'live_ai_calls':0,'paypal_calls':0}),flush=True)
            time.sleep(180)
    except Exception as exc:
        report.update(passed=False, failure_type=type(exc).__name__)
        raise
    finally:
        stop_web()
        if pg_started:
            pg('stop')
        report_name = ('public-interactive-browser-qa.json' if args.browser_qa else
                       'public-interactive-verification-no-live.json' if args.no_live else
                       'public-interactive-verification.json')
        report_path = args.report_file if args.report_file else Path(report_name)
        if not report_path.is_absolute():
            report_path = ROOT / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report['report_output'] = str(report_path.relative_to(ROOT)) if report_path.is_relative_to(ROOT) else 'external path'
        report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        try:
            import shutil
            shutil.rmtree(scratch)
        except OSError:
            pass
        print(json.dumps(report, indent=2))
    if not report.get('passed', False):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
