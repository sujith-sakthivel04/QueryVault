import os
import psycopg
from psycopg.rows import dict_row
from settings import load_local_environment
from decimal import Decimal
from firewall import QueryFirewall,PolicyError
load_local_environment()

def connect(reader=False, *, dsn=None):
    key = "READER_DATABASE_URL" if reader else "DATABASE_URL"
    value=dsn or os.getenv(key)
    if not value:
        raise psycopg.OperationalError('Local database configuration is missing; run bootstrap.py')
    return psycopg.connect(value, row_factory=dict_row, connect_timeout=5)

def read_query(sql, explain=False, *, reader_url=None):
    sql=QueryFirewall().validate(sql)
    with connect(reader=True, dsn=reader_url) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout = '2000ms'")
        conn.execute("SET LOCAL lock_timeout = '250ms'")
        conn.execute("SET LOCAL search_path = vault_data, pg_catalog")
        conn.execute("SET LOCAL work_mem = '4MB'")
        plan=conn.execute('EXPLAIN (FORMAT JSON) '+sql).fetchone()['QUERY PLAN'][0]['Plan']
        if Decimal(str(plan['Total Cost']))>10000:
            raise PolicyError('Query exceeds maximum permitted estimated planning cost')
        return plan if explain else conn.execute(sql).fetchmany(100)
