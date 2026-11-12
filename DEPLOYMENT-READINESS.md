# QueryVault deployment readiness

**Audit update (November 12, 2026).** The final source audit passed 213 backend tests and 26 subtests against isolated PostgreSQL, 38 frontend tests, and a clean Docker dependency install and production build. The clean image passed an AI-disabled Option B HTTP smoke test. The earlier Docker/Linux staging rehearsal and guest browser workflow are documented in [DEPLOYMENT-GATE-REPORT.md](DEPLOYMENT-GATE-REPORT.md).

Prepared locally on November 10, 2026. **Nothing was deployed, published, pushed, submitted or recorded. No PayPal request was made.** The optional B2 implementation and its bounded Groq verification are documented separately in [OPTION-B-READINESS.md](OPTION-B-READINESS.md). Existing $1.05 Sandbox capture, separate $0 void evidence and the genuine $0.50 versus $0.70 refusal are unchanged.

## Scope and deployment architecture

The existing React + FastAPI + PostgreSQL architecture remains. A multi-stage Dockerfile builds React once and copies its static output into the Python image. One Uvicorn process serves both UI and API from the same origin. PostgreSQL is separate persistent infrastructure. A one-shot administrative migration job precedes the web service; the web service receives only a restricted database reader secret. No Redis, queue, cloud SDK, hosted service or paid resource was introduced.

Three explicit modes have different security boundaries:

| Mode | Intended use | Authority |
|---|---|---|
| `local` (existing default) | Existing loopback single-operator development | Existing SQL workbench, Groq and Sandbox integration; local key/cookie; actual socket must be loopback |
| `public_demo` | Future restricted synthetic demonstration | Sanitized historical evidence and named read-only examples only; no operator sessions, user SQL, PayPal or live AI |
| `public_interactive` | Optional Phase B judge demonstration | Separate synthetic database, constrained AI proposal, firewall, deterministic quote, virtual-only allowance and accepted read-only execution; no PayPal or financial records |

`serve.py` requires explicit `public_demo` or `public_interactive` configuration and refuses local/default mode. Direct local Uvicorn startup remains supported, but is not the public production entrypoint. Do not place the local operator mode behind a public proxy. An authenticated, internet-facing paid product would require a separate identity/authorization design and is outside this change.

## Audit findings and implemented controls

| Previous deployment blocker | Result |
|---|---|
| Browser bootstrap granted operator key to any same-origin visitor | Disabled in public mode; local mode additionally checks the real socket peer, not forwarded headers |
| Local `.env` contained writer/provider/operator credentials | Public modes never load it and reject writer, operator and migration secrets; B2 accepts only its separately mounted provider-key file |
| Public web process could inherit database writer credentials | Public configuration requires a separate reader DSN/file; no writer or migration credentials are mounted into web |
| Arbitrary SQL preview and live agent/payment routes | Public router allowlist denies privileged routes at the backend, including with valid-looking local cookies/keys |
| Loopback hosts/origins hardcoded for every environment | Public mode validates one exact HTTPS origin and derives trusted host; loopback HTTP is allowed only for local tests |
| Static HTML mode did not handle SPA deep links | UI routes fall back to index, and buyer/seller selection is restored from the path on reload; unknown API, hidden/source files and missing assets remain 404; Windows separators handled |
| Local PostgreSQL setup assumed host tools/paths | Retained for local use; deployment migrations use ordinary PostgreSQL connections, with no Windows path dependency |
| Health could reveal external-service configuration | Public health reports disabled capabilities; separate liveness/readiness return minimal status and 503 on outage |
| No explicit production startup/shutdown bounds | One worker, 16 concurrent requests, 5-second keepalive, 10-second graceful drain; ASGI lifespan records stopping state |
| No public-demo abuse limits | B1 named examples are rate/concurrency limited; B2 adds durable global/per-visitor request and inference quotas, shared atomic reservations, token/call ceilings and persisted execution slots |
| Mutable app filesystem assumptions | Runtime needs no writes; Compose web is read-only, non-root UID 10001, with temporary storage only |

Public JSON errors and unexpected-error logs omit connection strings, request bodies, cookies, provider responses and secret values. Production access logging is disabled so callback/query URLs are not logged. Local PayPal diagnostic behavior is retained for the existing integration and must remain private.

## Safe public-demo behavior

Allowed API routes: GET `/api/config`, `/health`, `/health/live`, `/health/ready`, `/catalogue`, `/evaluation`, `/demo/evidence`; POST `/demo/query`. Production API docs/OpenAPI are disabled. Operator, session/history, quote/execute, recovery/reconciliation, PayPal return/status and live-agent routes are denied. The static mount cannot turn unknown API URLs into a successful HTML response.

The two allowed request bodies are:

```json
{"template":"port_delays"}
```

```json
{"template":"shipment_count"}
```

The server selects the SQL; SQL text or extra fields are rejected. Both templates pass through the existing SQLGlot firewall and restricted read-only execution layer. Results are real synthetic database results with zero query charge and no financial session. Viewing evidence does not run a model or create a checkout. Public UI changes only reflect disabled capabilities and the fixed example; the design/layout was preserved.

Before readiness or an interactive example succeeds, the server checks reader role attributes/membership, forbidden financial-table privileges, schema/write/TEMP privileges, read-only defaults, and the **exact** reproducible 600-shipment / four-port / three-route fixture. A changed fixture or an overly privileged reader fails closed. A deliberate administrator can still change the database/host; this is not a substitute for protecting infrastructure credentials.

No public session cookie is minted. Local cookies remain HttpOnly and SameSite=Strict for loopback development. Public writes require the configured origin when an Origin header is supplied, reject cross-site Fetch Metadata, and receive no permissive CORS headers. Fixed examples also work with ordinary non-browser HTTP clients; their authority is the intentionally public, tightly limited template capability. Public responses use frame denial, nosniff, no-store, no-referrer and a CSP; HSTS is emitted for the HTTPS configuration. Inline styles are allowed for the existing grid; inline scripts are not.

## Optional public-interactive mode (Phase B)

`public_interactive` is a distinct fail-closed mode, not a frontend switch on `public_demo`. Its Compose overlay uses `queryvault_interactive_demo`, a dedicated PostgreSQL volume and restricted `qv_interactive_reader`, plus a separate persistent volume for SQLite WAL quotas. The database contains only synthetic logistics tables. Readiness verifies role grants, schema/fixture expectations and that the reader cannot see financial tables. Migration rejects a mismatched database or existing non-synthetic application records. The SQL reader gets no writer/admin credential.

The AI gateway takes one short, bounded natural-language objective per request and makes no tool calls. It rejects unsupported topics, raw SQL, oversized input and prompt-injection patterns before inference. Generated SQL is validated by the existing SQLGlot firewall and PostgreSQL `EXPLAIN`, then priced by the deterministic engine. A human must accept the quoted SQL hash and ceiling before execution. The execute route receives only a server-stored plan ID and repeats the checks immediately before a read-only query. A virtual allowance is recorded only in the quota store, never in PayPal sessions or the financial ledger. Historical PayPal evidence stays separately labeled.

Provider use is disabled unless `QUERYVAULT_INTERACTIVE_ENABLED=true` is explicitly set and the mounted `GROQ_API_KEY_FILE` is readable. The key is never included in public responses or access logs. Current limits and the immediate persistent `AI_DISABLED` marker are documented in [OPTION-B-READINESS.md](OPTION-B-READINESS.md). The default overlay sets AI off. The current design assumes one host, one Uvicorn worker and a durable local quota volume; it does not prove visitor identity or support horizontal scale.

The merged Compose configuration was inspected to confirm the B2 database name, separate PostgreSQL and quota volumes, and AI-off default. This November 10 entry predates the November 12 Docker/Linux staging rehearsal documented in [DEPLOYMENT-GATE-REPORT.md](DEPLOYMENT-GATE-REPORT.md), which verified container startup, secret mounts, persistence, restart, backup/restore, graceful shutdown and the B2 browser workflow. TLS proxy, public hosting and Internet ingress remain untested.

## Required infrastructure and configuration

Future hosting needs a Python/container runtime, PostgreSQL 18, persistent PostgreSQL storage, an HTTPS reverse proxy, private database connectivity, secrets, backups and process supervision. The provided Compose services bind web only to host loopback and do not publish the database. TLS, DNS and internet routing are intentionally not provisioned. Uvicorn ignores forwarded proxy headers; origin authorization uses the configured canonical origin, and rate limits are global rather than based on spoofable client IPs.

| Variable | Purpose / requirement |
|---|---|
| `QUERYVAULT_MODE=public_demo` | Required by production startup |
| `QUERYVAULT_PUBLIC_ORIGIN` | Exact HTTPS origin, no path/query/credentials/trailing slash; only localhost/127.0.0.1 may use HTTP for local testing |
| `QUERYVAULT_DATASET=synthetic-logistics-v1` | Explicit fixture intent; database contents are independently checked |
| `READER_DATABASE_URL` **or** `READER_DATABASE_URL_FILE` | Reader connection, never both; use a mounted secret file in Compose |
| `QUERYVAULT_HOST` | Bind interface; production entrypoint defaults to 127.0.0.1; container explicitly uses 0.0.0.0 |
| `PORT` | Valid port, default 8000 |
| `QUERYVAULT_HOST_PORT` | Compose host loopback port, default 8080 |
| `MIGRATION_DATABASE_URL` / `_FILE` | Administrative DSN for the migration job only; never web |
| `MIGRATION_DB_HOST/PORT/NAME/USER` and `MIGRATION_DB_PASSWORD` / `_FILE` | Alternative migration connection parameters used by Compose |
| `READER_DB_PASSWORD` / `_FILE` | Generated reader password for the migration job only |

Public web must not contain `LOCAL_API_KEY`, `DATABASE_URL`, PayPal/Groq credentials or administrative migration secrets. Do not use `env_file: .env` or mount the operator workspace into production. Do not put credentials in `VITE_*` variables, frontend code or command arguments. Managed/remote PostgreSQL connections should use certificate-validated TLS (`sslmode=verify-full` with the provider CA); local/private Compose connectivity was the only connection style exercised here.

## Database setup, persistence and migrations

Use a **new dedicated synthetic database**, never the operator database or a copy containing financial/agent records. `migrate_deployment.py` requires public-demo/fixture intent, uses a transactional advisory lock and bounded lock/statement timeouts, and refuses databases with existing session/quote/ledger/agent rows. It applies the existing repeatable migration, seeds synthetic records and creates/configures `qv_reader` with SELECT-only data grants and no financial-table access. Public endpoints never create financial records. No automatic migration, payment retry or stale-payment recovery occurs at web startup.

The deployment reader has a connection limit of eight, a two-second statement timeout, a 250ms lock timeout, no database TEMP privilege and a 16MB temporary-file cap. Every connection is scoped to a context manager and closed; no stale connection pool is retained through restarts. Existing quote signatures/reservations/settlement logic remain local and durable in PostgreSQL. Do not rotate the local quote-signing key as part of these public-demo steps.

Compose persists PostgreSQL under the named `postgres_data` volume at `/var/lib/postgresql`, matching the versioned data directory layout of the official PostgreSQL 18 image. Ordinary container restarts and `docker compose down` retain it. Removing volumes destroys that database: do not use `down -v` as a routine restart. Volume persistence is not a backup. Plan encrypted off-host backups and verify a restore before real hosting; no backup/restore or major-version upgrade claim was tested here. [Official PostgreSQL image storage guidance](https://docs.docker.com/guides/postgresql/immediate-setup-and-data-persistence/) and [PostgreSQL backup documentation](https://www.postgresql.org/docs/18/backup.html).

## Exact future startup instructions — not executed as a deployment

Docker path, when a working daemon is available and local/container operation is desired:

```powershell
Copy-Item .env.deploy.example .env.deploy
.\.venv\Scripts\python prepare_deployment.py
docker compose --env-file .env.deploy config --quiet
docker compose --env-file .env.deploy build
docker compose --env-file .env.deploy up -d
docker compose --env-file .env.deploy ps
```

The sample `.env.deploy` contains only a non-secret loopback origin/port. Review it before a future authorized hosting action. `prepare_deployment.py` creates ignored secret files once and refuses rotation/overwrite. On POSIX the containing directory is 0700; source files are read-only/readable for Compose's non-root file-backed secret mounts. Windows relies on host ACLs: verify private ownership/ACLs before use. Web receives only its reader URL secret; the migration job alone receives administrative/reader-password secrets. Compose uses file mounts, not an encrypted secret vault. [Docker Compose secret behavior](https://docs.docker.com/compose/how-tos/use-secrets/).

On Linux/macOS use `cp` and the local Python executable instead of the first two PowerShell commands. Docker builds the Linux runtime; host PostgreSQL tools are unnecessary for this path. Startup ordering waits for a healthy database and a successfully completed migration job. [Compose dependency semantics](https://docs.docker.com/reference/compose-file/services/).

Equivalent direct production-style startup (create a fresh PostgreSQL database and secret files first):

```powershell
$env:QUERYVAULT_MODE='public_demo'
$env:QUERYVAULT_DATASET='synthetic-logistics-v1'
$env:QUERYVAULT_PUBLIC_ORIGIN='http://127.0.0.1:8002'
$env:READER_DATABASE_URL_FILE='<absolute path to reader DSN secret>'
$env:MIGRATION_DATABASE_URL_FILE='<absolute path to admin DSN secret>'
$env:READER_DB_PASSWORD_FILE='<absolute path to generated reader password>'
.\.venv\Scripts\python migrate_deployment.py
# The web process must not inherit migration/operator/provider credentials.
Remove-Item Env:\MIGRATION_DATABASE_URL_FILE,Env:\READER_DB_PASSWORD_FILE
.\.venv\Scripts\python serve.py --check
$env:PORT='8002'
.\.venv\Scripts\python serve.py
```

Run this in a clean shell without operator/writer/PayPal/Groq environment variables. Production-mode imports do not read the workspace `.env`. Install the pinned requirements and build frontend first (`npm ci --legacy-peer-deps`, `npm run build` in frontend). The SQL schema, static build and sanitized evidence are required; historical raw evidence and `.local` are not. For non-Windows shells use `export`/`unset` with the same variable names.

Local operator development is unchanged: `python bootstrap.py`, then `start.ps1` (or the documented loopback Uvicorn command). Its `.env`, private PostgreSQL directory and external credentials remain separate from the deployment stack.

## Verification performed

- Full backend: **208 tests + 26 subtests passed**; the prior 174 + 26 suite is included, and the new public-interactive cases are covered.
- Frontend: **20 tests passed**, TypeScript and Vite production build passed; four new interactive-workflow tests were added. The lazy AG Grid bundle warning remains.
- Clean copied-checkout bootstrap: **9/9 passed** with a fresh venv/npm install/PostgreSQL and no private provider/payment keys; both full suites passed.
- Isolated deployment-style verification: **12/12 checks passed** using a new PostgreSQL cluster on 55434 and real `serve.py` HTTP service on loopback 8002. Fresh migration repeated; production validation accepted/rejected correctly; SPA/reload and API 404 behavior; anonymous privilege denial; SQL/origin/host/body limits; both real free examples; historical evidence; abrupt web restart/persistence; database outage/readiness 503 and recovery without web restart; zero financial/agent records; refusal to migrate an operator-record fixture.
- ASGI lifecycle startup/shutdown was tested. Windows process termination was used for the abrupt-restart check; a Linux/container SIGTERM drain was not exercised.
- The B2 isolated production-entrypoint test passed **13/13 checks** with one bounded real Groq call (saved result: 532 model tokens, firewall passed, $0.35 quote, affordable, read-only result 600). A separate AI-off test passed **10/10 checks**, and browser inspection verified an actual fallback result of 600 with zero AI or PayPal calls. Two real Groq calls total were made during the authorized implementation; the detailed successful record is separate from mocked tests.
- Local HTTP checks passed on a temporary loopback-only server: two fresh free read-only results, unsafe-query rejection, access control and existing 105-cent settled history reconciled with no outstanding reservation.
- Current SQL evaluation: 24/24 legitimate main queries executed, 26/26 adversarial inputs rejected, 5/5 independent legitimate holdouts accepted, 5/5 adversarial holdouts rejected and 20/20 known answers correct. `pip check` passed; clean npm install found zero known vulnerabilities.
- The November 12 Docker/Linux staging rehearsal built and ran the merged B2 configuration with an isolated database/quota volume and AI disabled by default. It verified container startup, secret mounts, persistence, restart, backup/restore, graceful shutdown and the browser workflow. No public TLS, cloud host, proxy, or Internet ingress was tested.
- Existing financial tests use mocks; no new order, authorization, capture, void or payment mutation occurred. Historical Sandbox and earlier live Groq evidence remain separate from mock suites and new B2 verification.

Machine-generated JSON/JUnit run artifacts are kept locally and excluded from the public candidate because several contain historical provider or transaction identifiers. The current Docker/browser outcome is in DEPLOYMENT-GATE-REPORT.md. The final audit report is a local owner handoff and is not part of the public source candidate. The earlier test counts below are historical and are not a current full-suite pass claim.

Reproduce locally without cloud services or external keys:

```powershell
.\.venv\Scripts\python -m pytest -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
.\.venv\Scripts\python reproduce.py
.\.venv\Scripts\python verify_deployment.py
```

The last two need host PostgreSQL tools and free loopback ports (55433/8001 and 55434/8002 respectively). They stop only their isolated services. They do not use real financial services. `verify_http.py --base-url http://127.0.0.1:8000` verifies an independently running local operator service without payments/models.

## Sizing and cost considerations — estimates, not purchased capacity

A low-traffic demo starting point is one shared vCPU and roughly 2GB RAM for a small self-managed web/PostgreSQL host, with at least 10GB persistent capacity plus backup space. Build-time memory can be higher; build off-host if necessary. These are planning assumptions, not load-tested limits. The web container cap is 1GB/one CPU; the PostgreSQL service also needs memory and disk headroom.

For budgeting only, allow approximately **US$15–40/month** for a small self-managed host plus modest backup/storage/traffic allowances, with substantial variation by provider, region, taxes and service choices. As a price-scale reference, DigitalOcean's published basic table lists a 2GiB/one-vCPU instance at US$12/month before optional extras; this is not a provider recommendation or an exact total estimate. Check current quotes before any purchase. A separately managed database, load balancer or high availability can increase costs. [Published price reference](https://www.digitalocean.com/pricing/droplets).

Public demo disables live AI and payments, so it consumes neither Groq inference nor PayPal API operations; hosting/network/storage can still incur charges. Free tiers can sleep or discard ephemeral storage and must not be assumed to provide durable PostgreSQL. Nothing was provisioned or paid for.

## What remains before actual hosting

1. Obtain explicit hosting approval and choose the provider/domain/budget separately.
2. Repeat the non-root secret ownership/mode, read-only filesystem, restart and SIGTERM checks on the approved Linux host; pin reviewed image digests before a release. The local Docker Desktop rehearsal passed, but its Windows-backed secret metadata is not a substitute for target-host verification.
3. Configure trusted TLS termination, canonical host/origin, private database networking/certificate validation, host secret ACLs, log retention and off-host backups; test restore and reverse-proxy behavior.
4. Apply edge request/connection/traffic limits and monitoring. App preview limits are per-process and reset on restart; keep one worker/replica until a shared or edge limit is provided. Public health/readiness endpoints and static traffic also need edge protection.
5. Exercise expected traffic on the selected hardware and confirm capacity/cost limits. No internet-scale denial-of-service or exhaustive penetration-test claim is made.
6. Keep historical evidence immutable and labeled. Public-demo restrictions must remain enabled. Reopening operator/payment/agent privileges to public visitors is not a deployment toggle; it requires real authentication/authorization work and a separate approved scope.

Existing AG Grid lazy-chunk warning, Starlette/httpx test-client deprecation and version-pinned Python requirements without package hashes remain documented. Full local functionality is preserved; internet-facing multi-tenant/payment operation is intentionally not certified. Deployment, publication, GitHub push, Devpost submission and video recording remain unperformed.
