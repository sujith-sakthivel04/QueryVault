"""The only public interactive capability: bounded, named synthetic examples."""
from collections import deque
from threading import Lock, BoundedSemaphore
from time import monotonic
from db import connect

TEMPLATES = {
    'port_delays': "SELECT p.name, ROUND(AVG(s.delay_hours), 2) AS average_delay_hours FROM shipments s JOIN ports p ON s.port_id=p.id WHERE s.shipped_on >= '2026-10-01' AND s.shipped_on < '2026-11-01' GROUP BY p.name ORDER BY average_delay_hours DESC",
    'shipment_count': 'SELECT COUNT(*) AS shipment_count FROM shipments',
}


class DemoAdmission:
    """Global per-process bound, independent of spoofable forwarded client IPs."""
    def __init__(self, limit=30, window=60, concurrent=2):
        self.limit, self.window = limit, window
        self.times, self.lock = deque(), Lock()
        self.slots = BoundedSemaphore(concurrent)

    def admit(self):
        with self.lock:
            now = monotonic()
            while self.times and self.times[0] <= now - self.window:
                self.times.popleft()
            if len(self.times) >= self.limit:
                return False
            self.times.append(now)
            return True


def verify_reader(reader_url, *, expected_database=None, expected_role=None):
    """Fail closed on writer/admin privileges or a changed synthetic fixture.

    Trusted metadata queries are fixed by the application, never user input.
    Read-only transaction defaults alone are not an authorization boundary.
    """
    with connect(reader=True, dsn=reader_url) as conn:
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL statement_timeout='2000ms'")
        identity = conn.execute('SELECT current_database() AS database,current_user AS role').fetchone()
        if expected_database and identity['database'] != expected_database:
            raise ValueError('Public reader is not connected to its dedicated synthetic database')
        if expected_role and identity['role'] != expected_role:
            raise ValueError('Public reader is not using the dedicated query-only role')
        role = conn.execute("SELECT rolsuper,rolcreaterole,rolcreatedb,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        if not role or any(role.values()):
            raise ValueError('Public reader must not have privileged role attributes')
        # Membership can enable SET ROLE even when default INHERIT is disabled.
        if conn.execute("SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user) LIMIT 1").fetchone():
            raise ValueError('Public reader must not have role memberships')
        grants = conn.execute("SELECT has_database_privilege(current_user,current_database(),'CREATE') AS create_database,has_database_privilege(current_user,current_database(),'TEMP') AS temp,has_schema_privilege(current_user,'public','CREATE') AS create_public,has_schema_privilege(current_user,'vault_data','CREATE') AS create_data,CASE WHEN to_regclass('public.sessions') IS NULL THEN false ELSE has_table_privilege(current_user,'public.sessions','SELECT,INSERT,UPDATE,DELETE') END AS sessions,CASE WHEN to_regclass('public.ledger') IS NULL THEN false ELSE has_table_privilege(current_user,'public.ledger','SELECT,INSERT,UPDATE,DELETE') END AS ledger,CASE WHEN to_regclass('public.quotes') IS NULL THEN false ELSE has_table_privilege(current_user,'public.quotes','SELECT,INSERT,UPDATE,DELETE') END AS quotes,CASE WHEN to_regclass('public.agent_runs') IS NULL THEN false ELSE has_table_privilege(current_user,'public.agent_runs','SELECT,INSERT,UPDATE,DELETE') END AS agents").fetchone()
        if any(grants.values()):
            raise ValueError('Public reader has excessive privileges')
        visible_external = conn.execute("SELECT table_schema,table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema','vault_data') LIMIT 1").fetchone()
        if visible_external:
            raise ValueError('Public reader can see tables outside the synthetic schema')
        if expected_database:
            actual_tables = {tuple(r.values()) for r in conn.execute("SELECT table_schema,table_name FROM information_schema.tables WHERE table_type='BASE TABLE' AND table_schema NOT IN ('pg_catalog','information_schema') ORDER BY table_schema,table_name")}
            if actual_tables != {('vault_data','ports'),('vault_data','routes'),('vault_data','shipments')}:
                raise ValueError('Interactive database contains tables outside the synthetic fixture')
        for table in ('ports', 'routes', 'shipments'):
            if conn.execute("SELECT has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE,TRUNCATE,TRIGGER') AS writable", ('vault_data.' + table,)).fetchone()['writable']:
                raise ValueError('Public reader can mutate synthetic data')
        if conn.execute('SHOW default_transaction_read_only').fetchone()['default_transaction_read_only'] != 'on':
            raise ValueError('Public reader default must be read-only')
        expected_ports = [(1,'Singapore','Singapore'),(2,'Rotterdam','Netherlands'),(3,'Chennai','India'),(4,'Long Beach','USA')]
        expected_routes = [(1,'Straits corridor',3400),(2,'Atlantic connection',9800),(3,'Pacific passage',11200)]
        if [tuple(r.values()) for r in conn.execute('SELECT id,name,country FROM vault_data.ports ORDER BY id')] != expected_ports:
            raise ValueError('Synthetic port fixture mismatch')
        if [tuple(r.values()) for r in conn.execute('SELECT id,name,distance_km FROM vault_data.routes ORDER BY id')] != expected_routes:
            raise ValueError('Synthetic route fixture mismatch')
        # Compare both directions, so extra or missing rows also fail readiness.
        fixture = "SELECT i AS id,1+(i%4) AS port_id,1+(i%3) AS route_id,date '2026-10-01'+(i%30) AS shipped_on,(i*7)%49 AS delay_hours,1+(i%20) AS containers FROM generate_series(1,600) i"
        mismatch = conn.execute(f"SELECT EXISTS ((SELECT * FROM vault_data.shipments EXCEPT ({fixture})) UNION ALL (({fixture}) EXCEPT SELECT * FROM vault_data.shipments)) AS mismatch").fetchone()['mismatch']
        if mismatch:
            raise ValueError('Synthetic shipment fixture mismatch')
