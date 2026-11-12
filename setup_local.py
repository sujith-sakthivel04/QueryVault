"""Create a private loopback PostgreSQL cluster using an existing Windows install."""
import os
from pathlib import Path
import secrets
import subprocess
import shutil
from urllib.parse import quote
from dotenv import dotenv_values
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parent
def postgres_bin():
    if os.getenv('PG_BIN'): return Path(os.environ['PG_BIN'])
    found=shutil.which('initdb')
    if found: return Path(found).parent
    installs=sorted((Path(os.environ.get('ProgramFiles','C:/Program Files'))/'PostgreSQL').glob('*/bin'),reverse=True)
    if installs: return installs[0]
    raise RuntimeError('Install PostgreSQL server tools or set PG_BIN to their bin directory; see README.md.')

BIN = postgres_bin()
DATA = ROOT / ".local" / os.getenv('QUERYVAULT_CLUSTER','pgdata')
PORT = int(os.getenv('QUERYVAULT_DB_PORT','55432'))
def executable(name): return str(BIN/(name+('.exe' if os.name=='nt' else '')))
env = ROOT / os.getenv('QUERYVAULT_ENV_FILE','.env')

def main():
    cfg = dict(dotenv_values(env)) if env.exists() else {}
    for key in ("DB_ADMIN_PASSWORD", "DB_APP_PASSWORD", "DB_READER_PASSWORD", "LOCAL_API_KEY"):
        if not cfg.get(key): cfg[key]=secrets.token_urlsafe(32)
    for key, role in (("DATABASE_URL", "qv_app"), ("READER_DATABASE_URL", "qv_reader")):
        password = cfg["DB_APP_PASSWORD" if role == "qv_app" else "DB_READER_PASSWORD"]
        cfg[key] = f"postgresql://{role}:{quote(password)}@127.0.0.1:{PORT}/queryvault"
    cfg.setdefault("PAYPAL_ENVIRONMENT", "sandbox")
    cfg.setdefault("PAYPAL_CLIENT_ID", "")
    cfg.setdefault("PAYPAL_SECRET", "")
    cfg.setdefault("GROQ_API_KEY", "")
    cfg.setdefault("GROQ_MODEL", "openai/gpt-oss-20b")
    # Quoting preserves #, spaces and backslashes in user-provided credentials.
    def dotenv_quote(value): return "'"+str(value or '').replace('\\','\\\\').replace("'","\\'")+"'"
    env.parent.mkdir(parents=True,exist_ok=True)
    env.write_text("\n".join(f'{k}={dotenv_quote(v)}' for k,v in cfg.items())+"\n",encoding='utf-8')
    if os.name!='nt': env.chmod(0o600)
    DATA.parent.mkdir(exist_ok=True)
    if not (DATA / "PG_VERSION").exists():
        pw = DATA.parent / "init-password"
        pw.write_text(cfg["DB_ADMIN_PASSWORD"])
        try:
            subprocess.run([executable('initdb'), "-D", str(DATA), "-U", "postgres", "-A", "scram-sha-256", "--pwfile", str(pw), "--encoding=UTF8", "--locale=C"], check=True, capture_output=True)
        finally:
            pw.unlink(missing_ok=True)
        with (DATA / "postgresql.conf").open("a") as out:
            out.write(f"\nlisten_addresses='127.0.0.1'\nport={PORT}\nmax_connections=40\n")
    status = subprocess.run([executable('pg_ctl'), "-D", str(DATA), "status"], capture_output=True)
    if status.returncode:
        subprocess.run([executable('pg_ctl'), "-D", str(DATA), "-l", str(DATA.parent / (DATA.name+'.log')), "-w", "start"], check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    admin = dict(host="127.0.0.1", port=PORT, user="postgres", password=cfg["DB_ADMIN_PASSWORD"])
    with psycopg.connect(**admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname='queryvault'").fetchone():
            conn.execute("CREATE DATABASE queryvault")
    with psycopg.connect(**admin, dbname="queryvault", autocommit=True) as conn:
        conn.execute((ROOT / "migrations.sql").read_text())
        for role, key in (("qv_app", "DB_APP_PASSWORD"), ("qv_reader", "DB_READER_PASSWORD")):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(sql.Identifier(role),sql.Literal(cfg[key])))
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute("REVOKE TEMPORARY ON DATABASE queryvault FROM PUBLIC")
        conn.execute("REVOKE ALL ON SCHEMA vault_data FROM PUBLIC")
        conn.execute("GRANT USAGE ON SCHEMA vault_data TO qv_reader")
        conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA vault_data TO qv_reader")
        conn.execute("ALTER ROLE qv_reader SET default_transaction_read_only=on")
        conn.execute("ALTER ROLE qv_reader SET search_path=vault_data,pg_catalog")
        conn.execute("ALTER ROLE qv_reader SET statement_timeout='2s'")
        conn.execute("ALTER ROLE qv_reader SET lock_timeout='250ms'")
        conn.execute("ALTER ROLE qv_reader SET temp_file_limit='16MB'")
        conn.execute("GRANT USAGE ON SCHEMA public TO qv_app")
        conn.execute("GRANT SELECT,INSERT,UPDATE ON sessions,quotes TO qv_app")
        conn.execute("GRANT SELECT,INSERT,UPDATE ON agent_runs TO qv_app")
        conn.execute("GRANT SELECT,INSERT ON ledger TO qv_app")
        conn.execute("GRANT USAGE ON SEQUENCE ledger_id_seq TO qv_app")
        conn.execute("ANALYZE vault_data.shipments")
    print(f"Local PostgreSQL ready at 127.0.0.1:{PORT}; private configuration saved without displaying secrets.")

if __name__ == "__main__":
    main()
