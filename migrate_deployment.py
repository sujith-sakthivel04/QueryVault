"""Repeatable synthetic database bootstrap; explicit administrative job only.

Never run against an operator database. Financial/history rows cause refusal.
The web process has no migration credentials and never invokes this module.
"""
import os
from pathlib import Path
import sys
import psycopg
from psycopg import sql
from settings import secret, ConfigurationError


def migrate(env=None):
    env=os.environ if env is None else env
    mode=env.get('QUERYVAULT_MODE')
    if mode not in ('public_demo','public_interactive') or env.get('QUERYVAULT_DATASET')!='synthetic-logistics-v1':
        raise ConfigurationError('Migration requires an explicitly isolated synthetic public database')
    reader_password=secret('READER_DB_PASSWORD',env)
    if len(reader_password)<24:
        raise ConfigurationError('Use a generated reader password of at least 24 characters')
    dsn=secret('MIGRATION_DATABASE_URL',env)
    if dsn:
        conn=psycopg.connect(dsn,connect_timeout=5)
    else:
        password=secret('MIGRATION_DB_PASSWORD',env)
        if not password or not env.get('MIGRATION_DB_HOST'):
            raise ConfigurationError('Migration credentials are required separately from the web service')
        conn=psycopg.connect(host=env['MIGRATION_DB_HOST'],port=int(env.get('MIGRATION_DB_PORT','5432')),
                             dbname=env.get('MIGRATION_DB_NAME','queryvault'),user=env.get('MIGRATION_DB_USER','qv_migrator'),password=password,connect_timeout=5)
    with conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='30s'")
        conn.execute('SELECT pg_advisory_xact_lock(71980261)')
        if mode=='public_interactive':
            if conn.info.dbname!='queryvault_interactive_demo':
                raise ConfigurationError('Interactive migration requires its dedicated queryvault_interactive_demo database')
            existing=conn.execute("SELECT table_schema,table_name FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema','vault_data') AND table_type='BASE TABLE'").fetchall()
            if existing:
                raise ConfigurationError('Interactive demo refuses databases containing non-synthetic application tables')
            reader_role='qv_interactive_reader'
            conn.execute((Path(__file__).parent/'migrations_synthetic.sql').read_text(encoding='utf-8'))
        else:
            reader_role='qv_reader'
            for table in ('sessions','ledger','quotes','agent_runs'):
                if conn.execute('SELECT to_regclass(%s)',('public.'+table,)).fetchone()[0]:
                    if conn.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM public.{})').format(sql.Identifier(table))).fetchone()[0]:
                        raise ConfigurationError('Refusing to migrate a database containing operator or financial records')
            conn.execute((Path(__file__).parent/'migrations.sql').read_text(encoding='utf-8'))
        if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(reader_role,)).fetchone():
            conn.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS CONNECTION LIMIT 8 PASSWORD {}').format(sql.Identifier(reader_role),sql.Literal(reader_password)))
        if conn.execute('SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s) LIMIT 1',(reader_role,)).fetchone():
            raise ConfigurationError('Reader role memberships require manual review')
        conn.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        conn.execute('REVOKE ALL ON SCHEMA vault_data FROM PUBLIC')
        conn.execute(sql.SQL('REVOKE CREATE,TEMPORARY ON DATABASE {} FROM PUBLIC,{}').format(sql.Identifier(conn.info.dbname),sql.Identifier(reader_role)))
        conn.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA vault_data FROM {}').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL('REVOKE CREATE ON SCHEMA public,vault_data FROM {}').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA vault_data TO {}').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA vault_data TO {}').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL('ALTER ROLE {} SET default_transaction_read_only=on').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL('ALTER ROLE {} SET search_path=vault_data,pg_catalog').format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL("ALTER ROLE {} SET statement_timeout='2s'").format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL("ALTER ROLE {} SET lock_timeout='250ms'").format(sql.Identifier(reader_role)))
        conn.execute(sql.SQL("ALTER ROLE {} SET temp_file_limit='16MB'").format(sql.Identifier(reader_role)))
        conn.execute('ANALYZE vault_data.shipments')


if __name__=='__main__':
    try:
        migrate()
        print('Synthetic public-demo schema and reader grants are ready. No payment records were created.')
    except Exception as exc:
        print(f'Deployment migration failed ({type(exc).__name__}); no credentials or server details are logged.',file=sys.stderr)
        raise SystemExit(1)
