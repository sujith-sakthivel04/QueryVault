import pytest
from firewall import QueryFirewall, PolicyError
from db import read_query

LEGIT = [
    "SELECT COUNT(*) AS n FROM shipments",
    "SELECT id, name FROM ports ORDER BY id",
    "SELECT AVG(delay_hours) AS mean FROM shipments",
    "SELECT SUM(containers) AS total FROM shipments",
    "SELECT MIN(delay_hours), MAX(delay_hours) FROM shipments",
    "SELECT port_id, COUNT(*) FROM shipments GROUP BY port_id",
    "SELECT route_id, AVG(delay_hours) AS delay FROM shipments GROUP BY route_id ORDER BY delay DESC",
    "SELECT * FROM shipments WHERE delay_hours > 24 LIMIT 5",
    "SELECT DISTINCT country FROM ports",
    "SELECT s.id, p.name FROM shipments s JOIN ports p ON s.port_id=p.id LIMIT 10",
    "SELECT s.id, r.name FROM shipments s JOIN routes r ON s.route_id=r.id LIMIT 10",
    "WITH x AS (SELECT port_id, COUNT(*) AS n FROM shipments GROUP BY port_id) SELECT * FROM x",
    "SELECT * FROM (SELECT id, name FROM ports) p ORDER BY id",
    "SELECT port_id, COUNT(*) FROM shipments GROUP BY port_id HAVING COUNT(*) > 5",
    "SELECT COUNT(*) FROM shipments WHERE shipped_on BETWEEN '2026-10-01' AND '2026-10-30'",
    "SELECT COALESCE(name, 'unknown') FROM ports",
    "SELECT ROUND(AVG(delay_hours), 2) FROM shipments",
    "SELECT COUNT(*) FROM shipments WHERE port_id IN (SELECT id FROM ports WHERE country='India')",
    "SELECT name FROM ports WHERE name ILIKE '%a%'",
    "SELECT id, CASE WHEN delay_hours > 24 THEN 'late' ELSE 'normal' END AS category FROM shipments LIMIT 4",
    # Handwritten holdout variants, not independent model-generated examples.
    "WITH a AS (SELECT id FROM ports), b AS (SELECT * FROM a) SELECT * FROM b",
    "SELECT id FROM vault_data.shipments ORDER BY id LIMIT 900",
    "SELECT COUNT(*) FROM shipments WHERE shipped_on >= '2026-10-01' AND shipped_on < '2026-11-01'",
    "SELECT * FROM ports WHERE country='India' OR country='USA'",
]
ATTACKS = [
    "DROP TABLE shipments", "DELETE FROM shipments", "UPDATE shipments SET containers=0",
    "INSERT INTO ports VALUES (9,'x','x')", "SELECT * FROM shipments; SELECT * FROM ports",
    "WITH x AS (DELETE FROM shipments RETURNING *) SELECT * FROM x",
    "SELECT * INTO stolen FROM shipments", "SELECT * FROM pg_catalog.pg_authid",
    "SELECT * FROM information_schema.tables", "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')", "SELECT set_config('role','postgres',false)",
    "SELECT * FROM shipments UNION SELECT * FROM shipments", "SELECT * FROM public.shipments",
    "SELECT secret FROM shipments", "SELECT id FROM shipments s JOIN ports p ON s.port_id=p.id",
    "WITH RECURSIVE x AS (SELECT 1 UNION ALL SELECT 1 FROM x) SELECT * FROM x",
    "SELECT * FROM shipments CROSS JOIN shipments s", "SELECT * FROM generate_series(1,9999999)",
    "SELECT * FROM shipments FOR UPDATE", "SELECT 'postgres'::regrole",
    "SELECT * FROM shipments OFFSET 999999", "SELECT * FROM shipments LIMIT (SELECT 5)",
    "SELECT public.abs(-1)", "COPY shipments TO '/tmp/x'", "SELECT lo_import('/tmp/x')",
]

@pytest.mark.parametrize('sql',LEGIT)
def test_legitimate(sql):
    approved = QueryFirewall().validate(sql)
    assert len(read_query(approved)) <= 100

@pytest.mark.parametrize('sql',ATTACKS)
def test_attack(sql):
    with pytest.raises(PolicyError):
        QueryFirewall().validate(sql)

def test_known_answers_and_reader_grants():
    assert read_query(QueryFirewall().validate(LEGIT[0])) == [{"n":600}]
    from db import connect
    with connect(True) as conn:
        with pytest.raises(Exception):
            conn.execute("DELETE FROM vault_data.shipments")
