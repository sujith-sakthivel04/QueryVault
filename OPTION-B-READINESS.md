# QueryVault Option B — secure interactive AI demo

**Audit update (November 12, 2026).** The final source audit passed 213 backend tests and 26 subtests on Docker/Linux with isolated PostgreSQL, and 38 frontend tests passed during the audit. A clean Docker build installed dependencies and built the frontend. The resulting image served the AI-disabled B2 preview against a fresh synthetic database and returned 600 shipments at zero charge. The earlier browser rehearsal is documented in [DEPLOYMENT-GATE-REPORT.md](DEPLOYMENT-GATE-REPORT.md).

**Status: implemented and ready for owner review. Not deployed and not certified for internet production.** The existing React + FastAPI + PostgreSQL architecture and local operator workflow are preserved. `public_demo` remains the restricted no-AI fallback. The new `public_interactive` mode is separate and opt-in.

No PayPal request or transaction was made for Option B. The verified $1.05 Sandbox settlement, separate $20/$0 void, and genuine $0.50-available/$0.70-quote refusal remain historical records. The public interaction uses only a virtual allowance and synthetic logistics data.

## What a visitor can do

1. Enter a logistics research question in plain language.
2. Receive a single server-generated AI proposal, including its explanation and SQL in expandable technical details.
3. See the SQL firewall decision and a deterministic quote based on PostgreSQL's plan.
4. Review the virtual allowance and explicitly accept that exact SQL hash and price ceiling.
5. Execute the accepted read-only plan against the isolated synthetic database and inspect the actual result.
6. See a clear refusal when the request is unsupported, unsafe, over budget, or needs a scope review.

The execute endpoint accepts only a stored `plan_id`; it accepts no SQL text or client-supplied price. Before execution, the server rechecks the visitor, state, expiry, SQL hash, firewall, read-only query plan and deterministic price. No PayPal button or payment endpoint is available in this mode.

## Modes and authority

| Mode | Purpose | Data and authority |
|---|---|---|
| `local` (Mode A) | Existing operator workspace, loopback only | Existing sessions, quote/execute, Groq and PayPal Sandbox integration; operator key and private database |
| `public_demo` (Mode B1) | Restricted public fallback | Sanitized historical evidence and two named, free synthetic queries; no live AI, operator data, arbitrary SQL or PayPal mutations |
| `public_interactive` (Mode B2) | Optional judge interaction | One constrained AI proposal, validated read-only SQL, deterministic quote and virtual-only allowance against a dedicated synthetic database; no financial records or PayPal mutations |

`serve.py` requires an explicit public mode. B2 requires the dedicated database name `queryvault_interactive_demo`, role `qv_interactive_reader`, a reader-DSN secret file, persistent quota path, exact public origin, and the `synthetic-logistics-v1` dataset. It rejects operator, database-writer, migration and PayPal credentials. Remote PostgreSQL reader connections require `sslmode=verify-full`. Public modes never load the local `.env`.

The separate B2 PostgreSQL database and volume are selected by `compose.interactive.yaml`; the base `public_demo` configuration remains the default. The reader role cannot access financial tables. Schema, grants, read-only role defaults and the exact 600-shipment/four-port/three-route fixture are checked before readiness. The AI gateway has no tools, filesystem access, network-fetch tool or database writer credential.

## API boundary and state

- `GET /interactive/state` returns the caller's allowance and quota state and establishes a random visitor cookie.
- `POST /interactive/plan` accepts an objective plus idempotency request ID. It does not execute the proposal.
- `POST /interactive/accept` requires the stored plan ID, SQL hash and accepted price ceiling.
- `POST /interactive/execute` requires only the accepted stored plan ID.
- `GET /interactive/plans/{plan_id}` returns only a plan owned by the caller's visitor identity.

The API is mounted only in `public_interactive`. Public backend route allowlists deny local operator, payment, settlement, ledger, raw quote/execute and local agent endpoints. Cookies assist with visitor separation; they are not a claim of production multi-tenant identity.

The UI labels the allowance **“Demo allowance — no real payment”** and separately says it does not represent PayPal authorization, escrow or held funds. Historical payment evidence remains labeled historical and does not suggest a live checkout.

## Provider and execution safeguards

Live public AI is disabled by default and requires an explicit operator setting plus a separately mounted server-only Groq key. Each request is preflighted against a logistics-only objective gate and prompt-injection/raw-SQL checks before a provider call. The planner makes one bounded request with no tools, up to 800 output tokens and a 12-second timeout. Provider errors are returned in a generic structured form.

The durable quota database uses SQLite WAL and atomic `BEGIN IMMEDIATE` reservations. It is separate from the SQL reader database and survives application restarts. Current hard limits are:

- 100 visitor identities over the lifetime of the quota database, with $3.00 virtual allowance per identity and a $300 aggregate virtual allowance ceiling.
- 12 AI calls/day and 49,152 reserved provider tokens/day, plus 120 calls and 491,520 reserved tokens over the lifetime of the quota database.
- 4,096 tokens reserved per call; 3 AI calls/day per visitor; 2 attempts per normalized objective.
- At most 2 simultaneous model requests and 2 simultaneous database executions.
- 120 read-only runs/day globally and 6/day per visitor.
- 240 requests/minute globally and 30/minute per visitor; the visitor limit supplements the global limit and is not treated as identity proof.
- Expiring execution/model leases, idempotent request IDs, atomic virtual-budget reservations and at-most-once execution state transitions.

An accepted reservation that expires is released from the virtual accounting; a query marked in progress is never automatically replayed. Missing or corrupt quota state blocks startup instead of silently resetting lifetime limits. The initial quota volume must be initialized explicitly once. The immediate kill switch is an `AI_DISABLED` marker on the persistent quota volume; disabling the feature flag and restarting keeps AI off. Fixed read-only examples remain available when AI is disabled.

## Configuration and operation

The Compose overlay requires a deployment interpolation file containing the exact origin and host port, and file-backed secrets for the interactive reader password, reader DSN and Groq key. Generate the B2-only secret-file skeleton with:

```powershell
.\.venv\Scripts\python.exe prepare_deployment.py --interactive
```

This local preparation command does not start services. Store the provider key only in the ignored mounted secret file. Keep `QUERYVAULT_INTERACTIVE_ENABLED=false` until the hosting environment, cost cap and owner approval are confirmed. Use `QUERYVAULT_MODE=public_interactive`, `QUERYVAULT_DATASET=synthetic-logistics-v1`, the exact `QUERYVAULT_PUBLIC_ORIGIN`, `READER_DATABASE_URL_FILE`, `GROQ_API_KEY_FILE`, and `QUERYVAULT_QUOTA_DB_PATH=/var/lib/queryvault/quota.sqlite3` as the B2 runtime configuration. Initialize the persistent quota volume explicitly using the `quota-init` service before starting the web service.

For an immediate stop on an already running B2 Compose service, create `/var/lib/queryvault/AI_DISABLED` in the web container's mounted quota volume. The marker is checked by every AI request and persists across restarts. Keep the normal enable flag false for continued shutdown, then recreate the service after any configuration change. Deleting or recreating the quota volume would erase durable global limits and visitor accounting; it is not a routine reset mechanism.

At the time of this earlier check, the Docker Desktop Linux engine was unavailable. The November 12 Docker/Linux staging follow-up later verified the image, runtime, secret mounts, quota persistence, restart, backup/restore, graceful shutdown and real browser workflow; see DEPLOYMENT-GATE-REPORT.md.

## Actual verification results

- Full backend suite: **208 tests + 26 subtests passed**. The original 174 + 26 deployment-readiness result is included; the B2 tests cover configuration isolation, prompt/SQL rejection, limits, atomic overspend, visitor reset, quote/hash tampering, duplicate execution, provider timeout, API route boundaries, restart persistence, missing-state startup failure and read-only result handling. A test-harness `NameError` discovered in the first full run was fixed before the passing rerun.
- Frontend: **20 tests passed** across four files; TypeScript and production Vite build passed. The existing lazy seller-dashboard chunk warning remains.
- Clean copied checkout: **9/9 checks passed** with a fresh Python environment, dependency install, PostgreSQL cluster and npm clean install; full backend and frontend tests passed without private provider/payment keys.
- Existing production-style public-demo integration: **12/12 checks passed**.
- B2 isolated production-entrypoint run with one real Groq request: **13/13 checks passed**. The saved successful record reports one call, 532 model tokens, firewall pass, deterministic quote $0.35, affordable decision and an actual result of 600 matching an independent reference. Two bounded real Groq calls total were made during implementation; no more than the authorized limit of three. The detailed saved report is `public-interactive-verification-live.json`.
- B2 isolated run with AI explicitly disabled: **10/10 checks passed**, including database separation, quotas, restart persistence and a fresh read-only result of 600. Browser inspection confirmed disabled AI controls and a live fallback result labeled as actual read-only data, with zero inference and zero PayPal calls.
- Local HTTP smoke test passed on a temporary loopback service: authentication boundary, two fresh zero-charge SQL responses, unsafe-query rejection, OpenAPI and persisted 105-cent settlement reconciliation with no outstanding reservation.
- SQL evaluation on real PostgreSQL: 24/24 main legitimate cases accepted and executed, 26/26 adversarial inputs rejected before execution, 5/5 independent legitimate holdouts accepted, 5/5 adversarial holdouts rejected, and 20/20 known answers matched.
- `pip check` passed, npm reported zero known vulnerabilities during the clean install, and merged Compose syntax/isolation checks passed.
- **No PayPal request** was made. No order, authorization, capture, void, payment session or financial ledger entry was created by B2 verification.

Raw JSON/JUnit run artifacts remain local and are excluded from the public source candidate because they contain provider, transaction, or environment detail. The current Docker/browser evidence is summarized in [DEPLOYMENT-GATE-REPORT.md](DEPLOYMENT-GATE-REPORT.md). The final audit report is a local owner handoff and is not part of the public source candidate.

## Remaining limitations before public deployment

- The quota database is designed for one durable local volume, one application worker and one host. Do not horizontally scale replicas or place SQLite state on an unverified network filesystem. A shared transactional quota service is needed before scale-out.
- Anonymous visitor cookies can be reset; lifetime visitor, call, token and allowance ceilings constrain aggregate consumption but do not establish person-level identity. An edge/WAF traffic limit and abuse monitoring are still needed.
- Internet load, penetration, cross-site proxy, TLS/domain, and target-host secret ownership checks remain open. Docker/Linux runtime and backup/restore passed in the local staging rehearsal.
- SQL validation and scope-change refusals are conservative, but natural-language semantic equivalence is not formally proven. The live Groq result is one finite integration observation, not an accuracy guarantee. The real $0.50-versus-$0.70 refusal remains honest historical evidence; no successful optimization is claimed.
- Existing warnings remain: a Starlette/httpx TestClient deprecation and a large lazy AG Grid bundle. Python dependency versions are pinned but package hashes are not included.
- No deployment, publication, video recording or Devpost submission occurred. Option B is ready for owner review and a separately approved deployment test, not a claim of internet-production readiness.
