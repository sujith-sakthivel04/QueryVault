"""Restricted public interactive API: one AI proposal, binding demo quote, safe execution."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import secrets
import time
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from demo_quota import QuotaError, visitor_digest
from demo_quota import RESERVED_TOKENS_PER_CALL
from engine import price_plan
from firewall import PolicyError, QueryFirewall
from public_agent import ObjectiveError, PlannerError, propose, validate_objective
from db import read_query
from public_demo import verify_reader


router = APIRouter()
COOKIE_NAME = "qv_demo_visitor"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlanBody(StrictBody):
    objective: str = Field(min_length=1, max_length=500)
    request_id: UUID


class AcceptBody(StrictBody):
    plan_id: str = Field(min_length=20, max_length=80)
    sql_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_price_cents: int = Field(ge=1, le=2000, strict=True)


class ExecuteBody(StrictBody):
    plan_id: str = Field(min_length=20, max_length=80)


def _settings(request: Request):
    cfg = request.app.state.settings
    if not cfg.public_interactive:
        raise HTTPException(404, "Interactive research is unavailable.")
    return cfg


def _visitor(request: Request, *, create: bool = False):
    store = request.app.state.interactive_store
    token = request.cookies.get(COOKIE_NAME, "")
    if token and len(token) <= 100:
        digest = visitor_digest(token)
        try:
            visitor = store.state(digest)
            return token, digest, visitor, False
        except QuotaError as exc:
            if exc.status != 401:
                raise
    if not create:
        raise QuotaError(401, "Open the interactive workspace before submitting a research question.", "visitor_required")
    token = secrets.token_urlsafe(32)
    digest = visitor_digest(token)
    return token, digest, store.state(digest), True


def _cookie(response: Response, request: Request, token: str, fresh: bool):
    if fresh:
        secure = urlsplit(request.app.state.settings.public_origin).scheme == "https"
        response.set_cookie(COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True,
                            secure=secure, samesite="strict", path="/")


def _enabled(request: Request) -> bool:
    cfg = request.app.state.settings
    store = request.app.state.interactive_store
    return cfg.interactive_enabled and not store.kill_switch_active(cfg.quota_kill_file)


def _quota_http(exc: QuotaError):
    raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.detail}) from None


def _public_state(wallet: dict, *, enabled: bool):
    return {"mode": "public_interactive", "enabled": enabled,
            "label": "Demo allowance — no real payment" if enabled else "Interactive AI is currently disabled",
            "allowance_cents": wallet.get("allowance_cents", 0),
            "spent_cents": wallet.get("spent_cents", 0),
            "reserved_cents": wallet.get("reserved_cents", 0),
            "available_cents": wallet.get("available_cents", 0),
            "daily_ai_calls_used": wallet.get("daily_ai_calls_used", 0),
            "daily_ai_calls_limit": wallet.get("daily_ai_calls_limit", 0),
            "daily_ai_tokens_reserved": wallet.get("daily_ai_tokens_reserved", 0),
            "daily_ai_tokens_limit": wallet.get("daily_ai_tokens_limit", 0),
            "lifetime_ai_calls_used": wallet.get("lifetime_ai_calls_used", 0),
            "lifetime_ai_calls_limit": wallet.get("lifetime_ai_calls_limit", 0),
            "lifetime_ai_tokens_reserved": wallet.get("lifetime_ai_tokens_reserved", 0),
            "lifetime_ai_tokens_limit": wallet.get("lifetime_ai_tokens_limit", 0),
            "visitor_ai_calls_used": wallet.get("visitor_ai_calls_used", 0),
            "visitor_ai_calls_limit": wallet.get("visitor_ai_calls_limit", 0),
            "daily_queries_used": wallet.get("daily_queries_used", 0),
            "daily_queries_limit": wallet.get("daily_queries_limit", 0),
            "visitor_queries_used": wallet.get("visitor_queries_used", 0),
            "visitor_queries_limit": wallet.get("visitor_queries_limit", 0)}


@router.get("/interactive/state")
def interactive_state(request: Request, response: Response):
    cfg = _settings(request)
    store = request.app.state.interactive_store
    try:
        token, digest, wallet, fresh = _visitor(request, create=True)
        store.admit_http(digest)
        secure = urlsplit(cfg.public_origin).scheme == "https"
        response.set_cookie(COOKIE_NAME, token, max_age=COOKIE_MAX_AGE, httponly=True,
                            secure=secure, samesite="strict", path="/")
        return _public_state(wallet, enabled=_enabled(request))
    except QuotaError as exc:
        _quota_http(exc)


@router.get("/interactive/plans/{plan_id}")
def interactive_plan_status(plan_id: str, request: Request):
    _settings(request)
    try:
        _token, digest, _wallet, _fresh = _visitor(request)
        request.app.state.interactive_store.admit_http(digest)
        proposal = request.app.state.interactive_store.plan_for(digest, plan_id)
        if proposal["state"] == "pending":
            raise QuotaError(409, "This proposal is still being processed.", "request_in_progress")
        if proposal["state"] == "executing":
            raise QuotaError(409, "This query already started; its status is uncertain and it will not be repeated.", "execution_in_progress")
        return request.app.state.interactive_store.replay(proposal)
    except QuotaError as exc:
        _quota_http(exc)


@router.post("/interactive/plan")
def interactive_plan(body: PlanBody, request: Request, response: Response):
    cfg = _settings(request)
    store = request.app.state.interactive_store
    if not _enabled(request):
        raise HTTPException(503, detail={"code": "ai_disabled", "message": "Interactive AI is disabled by the operator."})
    try:
        objective = validate_objective(body.objective)
        token, digest, _wallet, fresh = _visitor(request)
        store.admit_http(digest)
        plan_id, state = store.begin_plan(digest, str(body.request_id), objective)
        if state and "_slot_id" not in state:
            _cookie(response, request, token, fresh)
            return state
        slot_id = state["_slot_id"]
        try:
            proposal = propose(objective, api_key=cfg.provider_key, model=cfg.provider_model)
            tokens_used=proposal["tokens_used"]
            if tokens_used is not None and tokens_used>RESERVED_TOKENS_PER_CALL:
                store.disable_ai()
                raise PlannerError("Provider token usage exceeded the reserved safety ceiling. Interactive AI was disabled.")
            reason = proposal["reason"]
            if not proposal["supported"]:
                result = {"plan_id": plan_id, "state": "refused", "objective": objective,
                          "message": reason or "This question is not supported by the synthetic logistics dataset.",
                          "firewall": "not run", "quote": None, "technical": None,"model_tokens_used":tokens_used}
                store.finish_plan(plan_id, digest, state="refused", response=result, reason=reason, slot_id=slot_id,tokens_used=tokens_used)
                _cookie(response, request, token, fresh)
                return result
            if proposal["scope_changed"]:
                result = {"plan_id": plan_id, "state": "scope_review", "objective": objective,
                          "message": reason or "The proposal could change the requested scope; it was not quoted or executed.",
                          "firewall": "not run", "quote": None, "technical": None,"model_tokens_used":tokens_used}
                store.finish_plan(plan_id, digest, state="scope_review", response=result, reason=reason, slot_id=slot_id,tokens_used=tokens_used)
                _cookie(response, request, token, fresh)
                return result
            if not proposal["sql"]:
                result = {"plan_id": plan_id, "state": "refused", "objective": objective,
                          "message": reason or "No supported query was proposed. Nothing was executed.",
                          "firewall": "not run", "quote": None, "technical": None,"model_tokens_used":tokens_used}
                store.finish_plan(plan_id, digest, state="refused", response=result, reason=reason, slot_id=slot_id,tokens_used=tokens_used)
                _cookie(response, request, token, fresh)
                return result
            try:
                approved_sql = QueryFirewall().validate(proposal["sql"])
            except (PolicyError, ValueError):
                result = {"plan_id": plan_id, "state": "sql_rejected", "objective": objective,
                          "message": "The generated query did not pass the read-only SQL firewall. It was not quoted or executed.",
                          "firewall": "rejected", "quote": None, "technical": None,"model_tokens_used":tokens_used}
                store.finish_plan(plan_id, digest, state="sql_rejected", response=result, reason=reason, slot_id=slot_id,tokens_used=tokens_used)
                _cookie(response, request, token, fresh)
                return result
            # This exact, canonical SQL is planned against the dedicated reader.
            plan = read_query(approved_sql, explain=True, reader_url=cfg.reader_url)
            price = price_plan(plan)
            sql_hash = hashlib.sha256(approved_sql.encode("utf-8")).hexdigest()
            wallet = store.state(digest)
            expires = time.time() + 300
            quote = {"price_cents": price, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(),
                     "sql_hash": sql_hash, "accepted_ceiling_cents": price,
                     "available_cents": wallet["available_cents"],
                     "budget_decision": "affordable" if price <= wallet["available_cents"] else "over_budget"}
            state_name = "quote_ready" if price <= wallet["available_cents"] else "over_budget"
            message = ("The deterministic quote fits the remaining virtual allowance. Accept it to reserve the demo amount before execution."
                       if state_name == "quote_ready" else
                       "The full-scope query quote exceeds the remaining virtual allowance. It was not accepted or executed.")
            result = {"plan_id": plan_id, "state": state_name, "objective": objective,
                      "message": message, "explanation": reason, "firewall": "passed",
                      "model_tokens_used":tokens_used,
                      "quote": quote, "technical": {"sql": approved_sql,
                      "plan": {k: plan[k] for k in ("Node Type", "Total Cost", "Plan Rows", "Plan Width") if k in plan}}}
            store.finish_plan(plan_id, digest, state=state_name, response=result, sql=approved_sql,
                              sql_hash=sql_hash, price_cents=price, reason=reason,
                              plan_summary=result["technical"]["plan"], expires_at=expires, slot_id=slot_id,
                              tokens_used=tokens_used)
            _cookie(response, request, token, fresh)
            return result
        except Exception:
            store.finish_plan(plan_id, digest, state="provider_unavailable",
                              response={"plan_id": plan_id, "state": "provider_unavailable",
                                        "message": "The planner or quote service is unavailable. No query was executed."},
                              slot_id=slot_id)
            raise
    except ObjectiveError as exc:
        raise HTTPException(422, detail={"code": "unsupported_objective", "message": str(exc)}) from None
    except QuotaError as exc:
        _quota_http(exc)
    except PlannerError as exc:
        raise HTTPException(503, detail={"code": "provider_unavailable", "message": str(exc)}) from None
    except Exception:
        # The exception may contain SQL, DSNs, provider data or local paths.
        raise HTTPException(503, detail={"code": "planning_unavailable", "message": "Planning or quote verification failed safely. No query was executed."}) from None


@router.post("/interactive/accept")
def interactive_accept(body: AcceptBody, request: Request):
    _settings(request)
    if not _enabled(request):
        raise HTTPException(503, detail={"code": "ai_disabled", "message": "Interactive research is disabled by the operator."})
    try:
        _token, digest, _wallet, _fresh = _visitor(request)
        request.app.state.interactive_store.admit_http(digest)
        accepted = request.app.state.interactive_store.accept(
            digest, body.plan_id, body.sql_hash, body.accepted_price_cents)
        return {**accepted, "label": "Accepted demo allowance — no real payment"}
    except QuotaError as exc:
        _quota_http(exc)


@router.post("/interactive/execute")
def interactive_execute(body: ExecuteBody, request: Request):
    cfg = _settings(request)
    store = request.app.state.interactive_store
    if not _enabled(request):
        raise HTTPException(503, detail={"code": "ai_disabled", "message": "Interactive research is disabled by the operator."})
    slot_id = None
    try:
        _token, digest, _wallet, _fresh = _visitor(request)
        store.admit_http(digest)
        proposal = store.plan_for(digest, body.plan_id)
        if proposal["state"] in ("completed", "failed", "stale_quote"):
            return store.replay(proposal)
        if proposal["state"] == "executing":
            raise QuotaError(409, "This query has already started; it will not be run twice.", "execution_in_progress")
        if proposal["state"] != "accepted":
            raise QuotaError(409, "Accept the current quote before execution.", "acceptance_required")
        # Independently rerun the firewall and hash check immediately before
        # planning/execution. The request body has no SQL or price field.
        approved_sql = QueryFirewall().validate(proposal["sql"] or "")
        sql_hash = hashlib.sha256(approved_sql.encode("utf-8")).hexdigest()
        if not secrets.compare_digest(sql_hash, proposal["sql_hash"] or ""):
            raise QuotaError(409, "The stored query no longer matches its accepted quote.", "sql_binding_mismatch")
        verify_reader(cfg.reader_url, expected_database="queryvault_interactive_demo")
        plan = read_query(approved_sql, explain=True, reader_url=cfg.reader_url)
        current_price = price_plan(plan)
        claimed, slot_id = store.claim_execution(digest, body.plan_id, recomputed_price=current_price)
        if slot_id == "replay":
            return store.replay(claimed)
        if slot_id == "expired":
            raise QuotaError(409, "The accepted quote expired; its virtual reservation was released.", "quote_expired")
        if slot_id == "stale_price":
            raise QuotaError(409, "The query plan exceeded the accepted ceiling; the reservation was released and no query ran.", "price_ceiling_changed")
        rows = read_query(approved_sql, reader_url=cfg.reader_url)
        json_rows = json.loads(json.dumps(rows, default=str))
        charge = claimed["price_cents"] if json_rows else 0
        result = store.complete_execution(digest, body.plan_id, slot_id, rows=json_rows, charged_cents=charge)
        return {"plan_id": body.plan_id, "state": "completed", "objective": claimed["objective"],
                "message": "The accepted query completed against the restricted synthetic database.",
                "firewall": "passed again immediately before execution", "result": result,
                "allowance": store.state(digest)}
    except QuotaError as exc:
        _quota_http(exc)
    except Exception:
        if slot_id and slot_id != "replay":
            store.fail_execution(digest, body.plan_id, slot_id)
        else:
            # If reader verification or the second firewall failed after
            # acceptance but before the execution claim, release its reservation.
            try:
                store.abort_accepted(digest, body.plan_id)
            except Exception:
                pass
        raise HTTPException(503, detail={"code": "execution_failed", "message": "The read-only query could not be verified or completed. No real payment occurred; this proposal will not be run twice."}) from None

