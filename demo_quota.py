"""Durable, non-billing quotas and idempotent state for anonymous demo research.

This SQLite database is private application state. The PostgreSQL query reader
has no connection or permissions to it. Every shared counter is reserved under
BEGIN IMMEDIATE so concurrency and process restarts cannot reset the limits.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time


ALLOWANCE_CENTS = 300
MAX_VISITORS = 100
MAX_AI_CALLS_PER_DAY = 12
MAX_AI_TOKENS_PER_DAY = 49_152
MAX_LIFETIME_AI_CALLS = 120
MAX_LIFETIME_AI_TOKENS = 491_520
RESERVED_TOKENS_PER_CALL = 4_096
MAX_VISITOR_AI_CALLS_PER_DAY = 3
MAX_OBJECTIVE_ATTEMPTS = 2
MAX_MODEL_CONCURRENCY = 2
MAX_QUERY_CONCURRENCY = 2
MAX_QUERIES_PER_DAY = 120
MAX_VISITOR_QUERIES_PER_DAY = 6
MAX_GLOBAL_REQUESTS_PER_MINUTE = 240
MAX_VISITOR_REQUESTS_PER_MINUTE = 30
SLOT_LEASE_SECONDS = 20


class QuotaError(Exception):
    def __init__(self, status: int, detail: str, code: str = "quota_error"):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code


def visitor_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def objective_digest(objective: str) -> str:
    return hashlib.sha256(" ".join(objective.casefold().split()).encode("utf-8")).hexdigest()


def utc_day() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class DemoQuotaStore:
    """Atomic, persistent virtual-wallet and provider quota store."""

    def __init__(self, path: str | Path, *, allowance_cents: int = ALLOWANCE_CENTS):
        self.path = Path(path)
        self.allowance_cents = allowance_cents

    def _connect(self):
        if not self.path.is_absolute() or str(self.path) == ":memory:":
            raise RuntimeError("Durable demo quota storage must use an absolute file path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RuntimeError("Demo quota storage must not be a symbolic link")
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def _reader(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def initialize(self):
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS visitors (
                    visitor_hash TEXT PRIMARY KEY,
                    allowance_cents INTEGER NOT NULL,
                    spent_cents INTEGER NOT NULL DEFAULT 0,
                    reserved_cents INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    CHECK(allowance_cents >= 0 AND spent_cents >= 0 AND reserved_cents >= 0),
                    CHECK(spent_cents + reserved_cents <= allowance_cents)
                );
                CREATE TABLE IF NOT EXISTS daily (
                    day TEXT PRIMARY KEY,
                    visitors_issued INTEGER NOT NULL DEFAULT 0,
                    ai_calls INTEGER NOT NULL DEFAULT 0,
                    tokens_reserved INTEGER NOT NULL DEFAULT 0,
                    query_runs INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS objective_attempts (
                    visitor_hash TEXT NOT NULL REFERENCES visitors(visitor_hash),
                    objective_hash TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    PRIMARY KEY(visitor_hash, objective_hash)
                );
                CREATE TABLE IF NOT EXISTS plans (
                    plan_id TEXT PRIMARY KEY,
                    visitor_hash TEXT NOT NULL REFERENCES visitors(visitor_hash),
                    request_id TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    objective_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    sql TEXT,
                    sql_hash TEXT,
                    price_cents INTEGER,
                    reason TEXT NOT NULL DEFAULT '',
                    plan_json TEXT,
                    response_json TEXT,
                    result_json TEXT,
                    tokens_used INTEGER,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    accepted_at REAL,
                    UNIQUE(visitor_hash, request_id)
                );
                CREATE INDEX IF NOT EXISTS plans_objective ON plans(visitor_hash, objective_hash);
                CREATE TABLE IF NOT EXISTS active_slots (
                    slot_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS preview_events (
                    visitor_hash TEXT NOT NULL REFERENCES visitors(visitor_hash),
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS request_windows (
                    window_key TEXT PRIMARY KEY,
                    window_start INTEGER NOT NULL,
                    count INTEGER NOT NULL
                );
            """)
            if 'tokens_used' not in {row[1] for row in conn.execute('PRAGMA table_info(plans)')}:
                conn.execute('ALTER TABLE plans ADD COLUMN tokens_used INTEGER')
            for key, value in (("schema_version", "1"), ("visitors_issued", "0"),
                               ("allowance_issued_cents", "0"), ("ai_enabled", "1"),
                               ("lifetime_ai_calls", "0"), ("lifetime_ai_tokens_reserved", "0")):
                conn.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (key, value))
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        finally:
            conn.close()
        try:
            if os.name != "nt":
                self.path.chmod(0o600)
                Path(str(self.path) + "-wal").chmod(0o600)
                Path(str(self.path) + "-shm").chmod(0o600)
        except FileNotFoundError:
            pass

    def validate(self):
        """Open existing initialized state only; never create quotas at web boot."""
        if self.path.is_symlink() or not self.path.is_file():
            raise RuntimeError("Persistent interactive quota state is missing or invalid")
        with self._reader() as conn:
            if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise RuntimeError("Persistent interactive quota state failed its integrity check")
            tables={row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            expected={'meta','visitors','daily','objective_attempts','plans','active_slots','preview_events','request_windows'}
            if tables != expected:
                raise RuntimeError("Persistent interactive quota state has an unknown schema")
            meta={row['key']:row['value'] for row in conn.execute('SELECT key,value FROM meta')}
            if (meta.get('schema_version')!='1' or meta.get('ai_enabled') not in ('0','1') or
                    'lifetime_ai_calls' not in meta or 'lifetime_ai_tokens_reserved' not in meta):
                raise RuntimeError("Persistent interactive quota state is not initialized")

    def kill_switch_active(self, marker: str | Path | None = None) -> bool:
        if marker is not None:
            try:
                with Path(marker).open("rb") as handle:
                    handle.read(1)
                return True
            except FileNotFoundError:
                pass
            except OSError:
                return True  # An unreadable switch fails closed.
        try:
            with self._reader() as conn:
                row = conn.execute("SELECT value FROM meta WHERE key='ai_enabled'").fetchone()
                return not row or row["value"] != "1"
        except (OSError, sqlite3.Error):
            return True

    def disable_ai(self):
        with self._transaction() as conn:
            conn.execute("UPDATE meta SET value='0' WHERE key='ai_enabled'")

    def enable_ai(self):
        with self._transaction() as conn:
            conn.execute("UPDATE meta SET value='1' WHERE key='ai_enabled'")

    def admit_http(self, visitor_hash: str):
        """Persistent rolling minute limits; forwarded IP headers are unused."""
        now = int(time.time())
        start = now // 60
        with self._transaction() as conn:
            for key, ceiling in (("global", MAX_GLOBAL_REQUESTS_PER_MINUTE),
                                 ("visitor:" + visitor_hash, MAX_VISITOR_REQUESTS_PER_MINUTE)):
                row = conn.execute("SELECT window_start,count FROM request_windows WHERE window_key=?", (key,)).fetchone()
                count = row["count"] if row and row["window_start"] == start else 0
                if count >= ceiling:
                    raise QuotaError(429, "Interactive request limit reached. Try again shortly.", "rate_limited")
                conn.execute("INSERT INTO request_windows(window_key,window_start,count) VALUES(?,?,?) "
                             "ON CONFLICT(window_key) DO UPDATE SET window_start=excluded.window_start,count=excluded.count",
                             (key, start, count + 1))

    def reserve_preview(self, visitor_hash: str) -> str:
        """Durably bound the existing fixed-template fallback's DB usage."""
        with self._transaction() as conn:
            if not conn.execute("SELECT 1 FROM visitors WHERE visitor_hash=?", (visitor_hash,)).fetchone():
                raise QuotaError(401, "Open the interactive workspace before using a preview.", "visitor_required")
            day = utc_day()
            usage = conn.execute("SELECT * FROM daily WHERE day=?", (day,)).fetchone()
            if usage and usage["query_runs"] >= MAX_QUERIES_PER_DAY:
                raise QuotaError(429, "The shared daily query execution limit is exhausted.", "global_query_limit")
            today = conn.execute("SELECT COUNT(*) FROM preview_events WHERE visitor_hash=? AND date(created_at,'unixepoch')=?", (visitor_hash, day)).fetchone()[0]
            plan_runs = conn.execute("SELECT COUNT(*) FROM plans WHERE visitor_hash=? AND state IN ('executing','completed','failed') AND date(created_at,'unixepoch')=?", (visitor_hash, day)).fetchone()[0]
            if today + plan_runs >= MAX_VISITOR_QUERIES_PER_DAY:
                raise QuotaError(429, "This visitor has reached today's query execution limit.", "visitor_query_limit")
            now = time.time()
            conn.execute("DELETE FROM active_slots WHERE expires_at<=?", (now,))
            if conn.execute("SELECT COUNT(*) FROM active_slots WHERE kind='query'").fetchone()[0] >= MAX_QUERY_CONCURRENCY:
                raise QuotaError(503, "The query service is busy. Try again shortly.", "query_busy")
            slot_id = secrets.token_urlsafe(24)
            conn.execute("INSERT INTO active_slots(slot_id,kind,expires_at) VALUES(?,'query',?)", (slot_id, now + SLOT_LEASE_SECONDS))
            conn.execute("INSERT INTO preview_events(visitor_hash,created_at) VALUES(?,?)", (visitor_hash, now))
            conn.execute("INSERT INTO daily(day,query_runs) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET query_runs=query_runs+1", (day,))
            return slot_id

    def release_slot(self, slot_id: str):
        with self._transaction() as conn:
            conn.execute("DELETE FROM active_slots WHERE slot_id=?", (slot_id,))

    def ensure_visitor(self, visitor_hash: str) -> dict:
        with self._transaction() as conn:
            row = conn.execute("SELECT * FROM visitors WHERE visitor_hash=?", (visitor_hash,)).fetchone()
            if not row:
                issued = int(conn.execute("SELECT value FROM meta WHERE key='visitors_issued'").fetchone()[0])
                allowance_issued = int(conn.execute("SELECT value FROM meta WHERE key='allowance_issued_cents'").fetchone()[0])
                if issued >= MAX_VISITORS or allowance_issued + self.allowance_cents > MAX_VISITORS * ALLOWANCE_CENTS:
                    raise QuotaError(429, "The shared demo allowance pool is fully assigned.", "allowance_pool_exhausted")
                conn.execute("INSERT INTO visitors(visitor_hash,allowance_cents,created_at) VALUES(?,?,?)",
                             (visitor_hash, self.allowance_cents, time.time()))
                conn.execute("UPDATE meta SET value=? WHERE key='visitors_issued'", (str(issued + 1),))
                conn.execute("UPDATE meta SET value=? WHERE key='allowance_issued_cents'",
                             (str(allowance_issued + self.allowance_cents),))
                conn.execute("INSERT INTO daily(day,visitors_issued) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET visitors_issued=visitors_issued+1", (utc_day(),))
                row = conn.execute("SELECT * FROM visitors WHERE visitor_hash=?", (visitor_hash,)).fetchone()
            return dict(row)

    def state(self, visitor_hash: str) -> dict:
        with self._transaction() as conn:
            self._expire_accepted(conn, visitor_hash)
        wallet = self.ensure_visitor(visitor_hash)
        with self._reader() as conn:
            day = conn.execute("SELECT * FROM daily WHERE day=?", (utc_day(),)).fetchone()
            meta = {row['key']:row['value'] for row in conn.execute("SELECT key,value FROM meta")}
            today_ai = conn.execute("SELECT COUNT(*) AS n FROM plans WHERE visitor_hash=? AND date(created_at,'unixepoch')=? AND state!='pending'", (visitor_hash, utc_day())).fetchone()["n"]
            today_queries = conn.execute("SELECT COUNT(*) AS n FROM plans WHERE visitor_hash=? AND date(created_at,'unixepoch')=? AND state IN ('executing','completed','failed','stale_quote')", (visitor_hash, utc_day())).fetchone()["n"]
            today_queries += conn.execute("SELECT COUNT(*) FROM preview_events WHERE visitor_hash=? AND date(created_at,'unixepoch')=?", (visitor_hash, utc_day())).fetchone()[0]
        return {
            "label": "Demo allowance — no real payment",
            "allowance_cents": wallet["allowance_cents"],
            "spent_cents": wallet["spent_cents"],
            "reserved_cents": wallet["reserved_cents"],
            "available_cents": wallet["allowance_cents"] - wallet["spent_cents"] - wallet["reserved_cents"],
            "daily_ai_calls_used": day["ai_calls"] if day else 0,
            "daily_ai_calls_limit": MAX_AI_CALLS_PER_DAY,
            "daily_ai_tokens_reserved": day["tokens_reserved"] if day else 0,
            "daily_ai_tokens_limit": MAX_AI_TOKENS_PER_DAY,
            "lifetime_ai_calls_used": int(meta["lifetime_ai_calls"]),
            "lifetime_ai_calls_limit": MAX_LIFETIME_AI_CALLS,
            "lifetime_ai_tokens_reserved": int(meta["lifetime_ai_tokens_reserved"]),
            "lifetime_ai_tokens_limit": MAX_LIFETIME_AI_TOKENS,
            "visitor_ai_calls_used": today_ai,
            "visitor_ai_calls_limit": MAX_VISITOR_AI_CALLS_PER_DAY,
            "daily_queries_used": day["query_runs"] if day else 0,
            "daily_queries_limit": MAX_QUERIES_PER_DAY,
            "visitor_queries_used": today_queries,
            "visitor_queries_limit": MAX_VISITOR_QUERIES_PER_DAY,
        }

    def _expire_accepted(self, conn, visitor_hash: str | None = None):
        now = time.time()
        query = "SELECT * FROM plans WHERE state='accepted' AND expires_at<?"
        params: tuple = (now,)
        if visitor_hash is not None:
            query += " AND visitor_hash=?"
            params = (now, visitor_hash)
        for plan in conn.execute(query, params).fetchall():
            self._release_reserved(conn, plan)
            response = json.loads(plan["response_json"] or "{}")
            response.update({"state": "stale_quote", "message": "The accepted quote expired before execution; its virtual reservation was released."})
            conn.execute("UPDATE plans SET state='stale_quote',response_json=? WHERE plan_id=?",
                         (json.dumps(response), plan["plan_id"]))

    def begin_plan(self, visitor_hash: str, request_id: str, objective: str) -> tuple[str, dict | None]:
        oid = objective_digest(objective)
        with self._transaction() as conn:
            existing = conn.execute("SELECT plan_id,state,response_json FROM plans WHERE visitor_hash=? AND request_id=?", (visitor_hash, request_id)).fetchone()
            if existing:
                if conn.execute("SELECT objective_hash FROM plans WHERE plan_id=?", (existing["plan_id"],)).fetchone()[0] != oid:
                    raise QuotaError(409, "This request identifier was already used for another objective.", "request_conflict")
                if existing["state"] == "provider_unavailable":
                    raise QuotaError(503, "The previous request failed safely and will not be retried with this identifier.", "provider_unavailable")
                if existing["response_json"]:
                    return existing["plan_id"], json.loads(existing["response_json"])
                raise QuotaError(409, "This research request is already being processed.", "request_in_progress")
            wallet = conn.execute("SELECT 1 FROM visitors WHERE visitor_hash=?", (visitor_hash,)).fetchone()
            if not wallet:
                raise QuotaError(401, "Start a demo visitor session before planning.", "visitor_required")
            if conn.execute("SELECT value FROM meta WHERE key='ai_enabled'").fetchone()[0] != "1":
                raise QuotaError(503, "Interactive AI is disabled by the operator.", "ai_disabled")
            day = utc_day()
            usage = conn.execute("SELECT * FROM daily WHERE day=?", (day,)).fetchone()
            calls, tokens, queries = (usage["ai_calls"], usage["tokens_reserved"], usage["query_runs"]) if usage else (0, 0, 0)
            if calls >= MAX_AI_CALLS_PER_DAY or tokens + RESERVED_TOKENS_PER_CALL > MAX_AI_TOKENS_PER_DAY:
                raise QuotaError(429, "The shared daily AI budget is exhausted.", "global_ai_budget_exhausted")
            lifetime_calls=int(conn.execute("SELECT value FROM meta WHERE key='lifetime_ai_calls'").fetchone()[0])
            lifetime_tokens=int(conn.execute("SELECT value FROM meta WHERE key='lifetime_ai_tokens_reserved'").fetchone()[0])
            if lifetime_calls>=MAX_LIFETIME_AI_CALLS or lifetime_tokens+RESERVED_TOKENS_PER_CALL>MAX_LIFETIME_AI_TOKENS:
                raise QuotaError(429, "The installation-wide AI allowance has been exhausted.", "lifetime_ai_budget_exhausted")
            visitor_calls = conn.execute("SELECT COUNT(*) FROM plans WHERE visitor_hash=? AND date(created_at,'unixepoch')=?", (visitor_hash, day)).fetchone()[0]
            if visitor_calls >= MAX_VISITOR_AI_CALLS_PER_DAY:
                raise QuotaError(429, "This visitor has reached today's AI planning limit.", "visitor_ai_limit")
            attempts = conn.execute("SELECT attempts FROM objective_attempts WHERE visitor_hash=? AND objective_hash=?", (visitor_hash, oid)).fetchone()
            if attempts and attempts[0] >= MAX_OBJECTIVE_ATTEMPTS:
                raise QuotaError(429, "This objective has reached its planning-attempt limit.", "objective_attempt_limit")
            now = time.time()
            conn.execute("DELETE FROM active_slots WHERE expires_at<=?", (now,))
            active = conn.execute("SELECT COUNT(*) FROM active_slots WHERE kind='inference'").fetchone()[0]
            if active >= MAX_MODEL_CONCURRENCY:
                raise QuotaError(503, "The research planner is busy. Try again shortly.", "model_busy")
            plan_id = secrets.token_urlsafe(24)
            slot_id = secrets.token_urlsafe(24)
            conn.execute("INSERT INTO daily(day,ai_calls,tokens_reserved) VALUES(?,?,?) ON CONFLICT(day) DO UPDATE SET ai_calls=ai_calls+1,tokens_reserved=tokens_reserved+excluded.tokens_reserved", (day, 1, RESERVED_TOKENS_PER_CALL))
            conn.execute("UPDATE meta SET value=? WHERE key='lifetime_ai_calls'", (str(lifetime_calls+1),))
            conn.execute("UPDATE meta SET value=? WHERE key='lifetime_ai_tokens_reserved'", (str(lifetime_tokens+RESERVED_TOKENS_PER_CALL),))
            conn.execute("INSERT INTO objective_attempts(visitor_hash,objective_hash,attempts) VALUES(?,?,1) ON CONFLICT(visitor_hash,objective_hash) DO UPDATE SET attempts=attempts+1", (visitor_hash, oid))
            conn.execute("INSERT INTO plans(plan_id,visitor_hash,request_id,objective,objective_hash,state,created_at) VALUES(?,?,?,?,?,'pending',?)", (plan_id, visitor_hash, request_id, objective, oid, now))
            conn.execute("INSERT INTO active_slots(slot_id,kind,expires_at) VALUES(?,'inference',?)", (slot_id, now + SLOT_LEASE_SECONDS))
            return plan_id, {"_slot_id": slot_id}

    def finish_plan(self, plan_id: str, visitor_hash: str, *, state: str, response: dict,
                    sql: str | None = None, sql_hash: str | None = None, price_cents: int | None = None,
                    reason: str = "", plan_summary: dict | None = None, expires_at: float | None = None,
                    slot_id: str | None = None, tokens_used: int | None = None):
        with self._transaction() as conn:
            conn.execute("UPDATE plans SET state=?,sql=?,sql_hash=?,price_cents=?,reason=?,plan_json=?,response_json=?,expires_at=?,tokens_used=? WHERE plan_id=? AND visitor_hash=? AND state='pending'",
                         (state, sql, sql_hash, price_cents, reason[:600], json.dumps(plan_summary, separators=(",", ":")) if plan_summary else None,
                          json.dumps(response, separators=(",", ":"), default=str), expires_at, tokens_used, plan_id, visitor_hash))
            if slot_id:
                conn.execute("DELETE FROM active_slots WHERE slot_id=? AND kind='inference'", (slot_id,))

    def accept(self, visitor_hash: str, plan_id: str, sql_hash: str, accepted_price: int) -> dict:
        with self._transaction() as conn:
            self._expire_accepted(conn, visitor_hash)
            plan = conn.execute("SELECT * FROM plans WHERE plan_id=? AND visitor_hash=?", (plan_id, visitor_hash)).fetchone()
            if not plan:
                raise QuotaError(404, "Research proposal not found for this visitor.", "plan_not_found")
            if plan["state"] in ("accepted", "executing", "completed", "failed", "stale_quote"):
                return {"plan_id": plan_id, "state": plan["state"], "accepted_price_cents": plan["price_cents"]}
            if plan["state"] != "quote_ready":
                raise QuotaError(409, "This proposal is not eligible for acceptance.", "plan_not_acceptable")
            if plan["expires_at"] is None or plan["expires_at"] < time.time():
                raise QuotaError(409, "The quote expired. Request a fresh proposal.", "quote_expired")
            if not secrets.compare_digest(str(plan["sql_hash"] or ""), sql_hash) or plan["price_cents"] != accepted_price:
                raise QuotaError(409, "The accepted SQL hash and price must match the server quote exactly.", "quote_binding_mismatch")
            wallet = conn.execute("SELECT * FROM visitors WHERE visitor_hash=?", (visitor_hash,)).fetchone()
            available = wallet["allowance_cents"] - wallet["spent_cents"] - wallet["reserved_cents"]
            if plan["price_cents"] > available:
                raise QuotaError(409, "The quoted plan exceeds the remaining demo allowance.", "over_budget")
            conn.execute("UPDATE visitors SET reserved_cents=reserved_cents+? WHERE visitor_hash=?", (plan["price_cents"], visitor_hash))
            response = json.loads(plan["response_json"] or "{}")
            response.update({"state": "accepted", "message": "The quoted amount is reserved from this virtual demo allowance. No payment was made."})
            conn.execute("UPDATE plans SET state='accepted',accepted_at=?,response_json=? WHERE plan_id=?",
                         (time.time(), json.dumps(response), plan_id))
            return {"plan_id": plan_id, "state": "accepted", "accepted_price_cents": plan["price_cents"]}

    def claim_execution(self, visitor_hash: str, plan_id: str, *, recomputed_price: int) -> tuple[dict, str]:
        with self._transaction() as conn:
            self._expire_accepted(conn, visitor_hash)
            plan = conn.execute("SELECT * FROM plans WHERE plan_id=? AND visitor_hash=?", (plan_id, visitor_hash)).fetchone()
            if not plan:
                raise QuotaError(404, "Research proposal not found for this visitor.", "plan_not_found")
            if plan["state"] in ("completed", "failed", "stale_quote"):
                return dict(plan), "replay"
            if plan["state"] != "accepted":
                if plan["state"] == "executing":
                    raise QuotaError(409, "This query has already started; it will not be run twice.", "execution_in_progress")
                raise QuotaError(409, "Accept the current quote before execution.", "acceptance_required")
            if plan["expires_at"] is None or plan["expires_at"] < time.time():
                self._release_reserved(conn, plan)
                response = json.loads(plan["response_json"] or "{}")
                response.update({"state": "stale_quote", "message": "The accepted quote expired; its virtual reservation was released."})
                conn.execute("UPDATE plans SET state='stale_quote',response_json=? WHERE plan_id=?", (json.dumps(response), plan_id))
                return dict(plan), "expired"
            if recomputed_price > plan["price_cents"]:
                self._release_reserved(conn, plan)
                response = json.loads(plan["response_json"] or "{}")
                response.update({"state": "stale_quote", "message": "The database plan changed above the accepted ceiling; its virtual reservation was released and no query ran."})
                conn.execute("UPDATE plans SET state='stale_quote',response_json=? WHERE plan_id=?", (json.dumps(response), plan_id))
                return dict(plan), "stale_price"
            day = utc_day()
            usage = conn.execute("SELECT * FROM daily WHERE day=?", (day,)).fetchone()
            if usage and usage["query_runs"] >= MAX_QUERIES_PER_DAY:
                raise QuotaError(429, "The shared daily query execution limit is exhausted.", "global_query_limit")
            visitor_runs = conn.execute("SELECT COUNT(*) FROM plans WHERE visitor_hash=? AND state IN ('executing','completed','failed','stale_quote') AND date(created_at,'unixepoch')=?", (visitor_hash, day)).fetchone()[0]
            visitor_runs += conn.execute("SELECT COUNT(*) FROM preview_events WHERE visitor_hash=? AND date(created_at,'unixepoch')=?", (visitor_hash, day)).fetchone()[0]
            if visitor_runs >= MAX_VISITOR_QUERIES_PER_DAY:
                raise QuotaError(429, "This visitor has reached today's query execution limit.", "visitor_query_limit")
            now = time.time()
            conn.execute("DELETE FROM active_slots WHERE expires_at<=?", (now,))
            if conn.execute("SELECT COUNT(*) FROM active_slots WHERE kind='query'").fetchone()[0] >= MAX_QUERY_CONCURRENCY:
                raise QuotaError(503, "The query service is busy. Try again shortly.", "query_busy")
            slot_id = secrets.token_urlsafe(24)
            conn.execute("INSERT INTO active_slots(slot_id,kind,expires_at) VALUES(?,'query',?)", (slot_id, now + SLOT_LEASE_SECONDS))
            conn.execute("UPDATE plans SET state='executing' WHERE plan_id=? AND state='accepted'", (plan_id,))
            conn.execute("INSERT INTO daily(day,query_runs) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET query_runs=query_runs+1", (day,))
            plan = dict(conn.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone())
            return plan, slot_id

    @staticmethod
    def _release_reserved(conn, plan):
        if plan["price_cents"]:
            conn.execute("UPDATE visitors SET reserved_cents=MAX(0,reserved_cents-?) WHERE visitor_hash=?", (plan["price_cents"], plan["visitor_hash"]))

    def complete_execution(self, visitor_hash: str, plan_id: str, slot_id: str, *, rows: list, charged_cents: int):
        result = {"rows": rows, "charged_cents": charged_cents, "mode": "public_interactive",
                  "label": "Virtual demo allowance — no real payment"}
        with self._transaction() as conn:
            plan = conn.execute("SELECT * FROM plans WHERE plan_id=? AND visitor_hash=? AND state='executing'", (plan_id, visitor_hash)).fetchone()
            if not plan:
                raise QuotaError(409, "The query result could not be committed; do not retry this proposal.", "execution_state_lost")
            self._release_reserved(conn, plan)
            conn.execute("UPDATE visitors SET spent_cents=spent_cents+? WHERE visitor_hash=?", (charged_cents, visitor_hash))
            response = json.loads(plan["response_json"] or "{}")
            response.update({"state": "completed", "result": result})
            conn.execute("UPDATE plans SET state='completed',result_json=?,response_json=? WHERE plan_id=?",
                         (json.dumps(result, separators=(",", ":"), default=str), json.dumps(response, separators=(",", ":"), default=str), plan_id))
            conn.execute("DELETE FROM active_slots WHERE slot_id=?", (slot_id,))
        return result

    def fail_execution(self, visitor_hash: str, plan_id: str, slot_id: str):
        with self._transaction() as conn:
            plan = conn.execute("SELECT * FROM plans WHERE plan_id=? AND visitor_hash=? AND state='executing'", (plan_id, visitor_hash)).fetchone()
            if plan:
                self._release_reserved(conn, plan)
                response = json.loads(plan["response_json"] or "{}")
                response.update({"state": "failed", "message": "The read-only query did not complete; no demo allowance was charged."})
                conn.execute("UPDATE plans SET state='failed',response_json=? WHERE plan_id=?", (json.dumps(response), plan_id))
            conn.execute("DELETE FROM active_slots WHERE slot_id=?", (slot_id,))

    def abort_accepted(self, visitor_hash: str, plan_id: str):
        """Release a reservation if pre-execution verification fails."""
        with self._transaction() as conn:
            plan = conn.execute("SELECT * FROM plans WHERE plan_id=? AND visitor_hash=? AND state='accepted'", (plan_id, visitor_hash)).fetchone()
            if plan:
                self._release_reserved(conn, plan)
                response = json.loads(plan["response_json"] or "{}")
                response.update({"state": "failed", "message": "Pre-execution verification failed; the virtual reservation was released. No query ran."})
                conn.execute("UPDATE plans SET state='failed',response_json=? WHERE plan_id=?", (json.dumps(response), plan_id))

    def replay(self, plan: dict) -> dict:
        if plan.get("response_json"):
            return json.loads(plan["response_json"])
        raise QuotaError(409, "This query has already been attempted and will not run twice.", "execution_already_attempted")

    def plan_for(self, visitor_hash: str, plan_id: str) -> dict:
        with self._reader() as conn:
            row = conn.execute("SELECT * FROM plans WHERE plan_id=? AND visitor_hash=?", (plan_id, visitor_hash)).fetchone()
        if not row:
            raise QuotaError(404, "Research proposal not found for this visitor.", "plan_not_found")
        return dict(row)

