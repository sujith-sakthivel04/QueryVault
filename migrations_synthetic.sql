-- Dedicated interactive-demo schema. Deliberately contains no commercial,
-- session, authorization, query-ledger, or payment tables.
CREATE SCHEMA IF NOT EXISTS vault_data;
REVOKE ALL ON SCHEMA vault_data FROM PUBLIC;
CREATE TABLE IF NOT EXISTS vault_data.ports(id int PRIMARY KEY, name text, country text);
CREATE TABLE IF NOT EXISTS vault_data.routes(id int PRIMARY KEY, name text, distance_km int);
CREATE TABLE IF NOT EXISTS vault_data.shipments(id int PRIMARY KEY, port_id int REFERENCES vault_data.ports, route_id int REFERENCES vault_data.routes, shipped_on date, delay_hours int, containers int);
INSERT INTO vault_data.ports VALUES (1,'Singapore','Singapore'),(2,'Rotterdam','Netherlands'),(3,'Chennai','India'),(4,'Long Beach','USA') ON CONFLICT DO NOTHING;
INSERT INTO vault_data.routes VALUES (1,'Straits corridor',3400),(2,'Atlantic connection',9800),(3,'Pacific passage',11200) ON CONFLICT DO NOTHING;
INSERT INTO vault_data.shipments SELECT i,1+(i%4),1+(i%3),date '2026-10-01'+(i%30),(i*7)%49,1+(i%20) FROM generate_series(1,600) i ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS shipments_date_idx ON vault_data.shipments(shipped_on);
