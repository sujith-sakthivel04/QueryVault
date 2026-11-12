# QueryVault Option B — final verification

**Assessment date:** November 11, 2026  
**Original November 11 release gate:** **Conditionally ready** for a controlled staging rehearsal after the infrastructure conditions below were met. It was not cleared for public Internet exposure.

**November 12 staging follow-up:** The Docker/Linux staging rehearsal, latest production frontend, real browser workflow, restart/shutdown, and volume backup/restore were subsequently verified. The current deployment gate and remaining blockers are in [DEPLOYMENT-GATE-REPORT.md](DEPLOYMENT-GATE-REPORT.md). Statements below about the unavailable Docker Engine and uninspected B2 browser are the historical November 11 snapshot and are superseded by that follow-up.

## Scope and safety

This pass exercised the actual `public_interactive` application factory and `serve.py` against a fresh, disposable local PostgreSQL cluster, database `queryvault_interactive_demo`, and restricted reader `qv_interactive_reader`. The cluster contained only the reproducible synthetic logistics dataset. The quota SQLite file and temporary provider-key file were isolated to that run. The interactive provider was a deterministic in-process mock; the provider key was a test sentinel, not a usable credential. A second run exercised the disabled-AI path. Neither run read the local operator `.env` or connected to the operator database.

No PayPal request or new Groq inference was made. B2 verification created no financial tables, payment sessions, or financial ledger entries. Historical live-provider reports remain historical evidence only.

## Verified now

### B2 application and frontend integration

- The mock-provider production-entrypoint run passed **45/45 checks**. The separate AI-disabled run passed **16/16 checks**. Both used real FastAPI HTTP routes, the latest Vite build, the dedicated PostgreSQL fixture, the restricted reader, and isolated quota state.
- HTTP checks served the homepage, current favicon, manifest, brand SVG, and `/research` deep link. Guest access required no login. The application returned its current static build and route fallback. These are HTTP checks, not a visual browser inspection.
- The real database result for the accepted workflow was **600 shipments**, matching an independent reference query. The deterministic production quote was **35 virtual cents**. Acceptance bound the exact canonical SQL hash and quoted price; execution through the accepted-plan route returned the database result. Duplicate proposal reuse and duplicate execution did not call the provider again or spend twice.
- Direct client SQL in the execute request was rejected. A changed hash or price, pre-accept execution, stale/malformed input, and cross-origin requests were refused. The frontend execution response previously discarded quote and firewall evidence returned with the proposal; it now retains that evidence while displaying the actual executed SQL and result. A regression test covers the merge.
- Refusal checks covered raw-SQL objectives before provider invocation, firewall rejection with no quote/result, unsupported objectives, scope changes before quote, generic provider failure with no execution, oversized bodies, invalid input, untrusted hosts, insufficient allowance, and quota exhaustion. The disabled run retained the real fixed read-only fallback.
- Brand assets were missing from the Docker build context. `Dockerfile` and `.dockerignore` now include `frontend/public`, and a deployment regression test protects that asset path. The image itself could not be built because the Docker Engine is unavailable.
- The secure-cookie flag for an HTTPS canonical origin previously depended on the app's internal HTTP scheme behind a TLS proxy. It now derives from the configured public origin; a regression test covers that proxy arrangement.

### SQL, acceptance, and refusal controls

- The independent SQL evaluation on PostgreSQL 18 with its restricted reader accepted and executed **24/24** legitimate cases, rejected **26/26** adversarial cases before database execution, accepted **5/5** independent legitimate holdouts, rejected **5/5** adversarial holdouts, and matched **20/20** known answers.
- The independent holdout was generated on November 9, 2026. Its provenance is historical; this pass made no Groq request. The SQL evaluation used the local restricted read-only reader in a separate evaluation process; it was not used as the B2 database. B2 itself used the new isolated database described above.
- Public SQL remains restricted to the SQL firewall, an `EXPLAIN` plan-cost check, a read-only PostgreSQL transaction, the `vault_data` search path, a 2-second statement timeout, a 250-ms lock timeout, and a 100-row result ceiling. Rejected SQL never reaches execution.

### Security and quotas

The public-route regression used a fake, valid-looking operator key/cookie sentinel and direct HTTP requests; it was not the local operator credential. Public configuration rejects operator credential variables before startup, and the public route boundary denied access. Operator session, seller, local-login, quote/execute, recovery, and reconciliation access remained denied. PayPal create/capture/void paths had no public handlers. Private evidence, environment files, source files, `/docs`, and `/openapi.json` were not served. Provider-key values were absent from public configuration. The B2 runtime created no commercial or financial tables.

Effective source limits for the current implementation:

| Limit | Configured ceiling |
|---|---:|
| Anonymous visitors / virtual allowance per visitor | 100 / $3.00 |
| Aggregate virtual allowance issued | $300.00 |
| AI requests / tokens, global per day | 12 / 49,152 |
| AI requests / tokens, installation lifetime | 120 / 491,520 |
| AI requests per visitor per day / objective attempts | 3 / 2 |
| Reserved tokens per inference / completion tokens | 4,096 / 800 |
| Provider timeout / retries | 12 seconds / 0 |
| Concurrent model calls / SQL executions | 2 / 2 |
| Read-only queries, global / visitor per day | 120 / 6 |
| HTTP requests, global / visitor per minute | 240 / 30 |
| Request body / objective | 16 KiB / 500 characters |
| Query rows / statement timeout / lock timeout | 100 / 2 seconds / 250 ms |
| Server workers / concurrent requests / shutdown grace | 1 / 16 / 10 seconds |

Inference and query reservation slots expire after 20 seconds; SQLite's connection/busy timeout is 5 seconds. The Compose web container is capped at 1 CPU, 1 GiB memory, and 128 PIDs; PostgreSQL shared memory is 128 MiB.

The B2 run verified two simultaneous model slots with a third request refused, lifetime quota exhaustion failing closed, a distinct unaffordable response without spending, and the AI kill switch. With the switch active, AI was refused while the fixed 600-row-count preview still worked and payment access remained unavailable. SQLite uses a durable file, WAL, and atomic `BEGIN IMMEDIATE` reservations. Missing/corrupt state fails closed. Web restarts retained the visitor allowance, plan, and result. A SQLite backup/restore reproduced the tested wallet, and a synthetic PostgreSQL dump/restore reproduced the reference data. These were isolated file/database drills, not Compose-volume or production recovery drills.

The B2 runtime exercised a generic provider-unavailable failure but did not trigger a live provider timeout or PostgreSQL statement timeout. Provider timeout handling is covered by the automated mocked backend suite; no new external request was made. A database outage/readiness failure and recovery were exercised in the isolated runtime. An unexpected internal-error response was not deliberately injected during this pass.

The same mock run stopped PostgreSQL: liveness stayed available, readiness returned 503, and readiness returned 200 after PostgreSQL restarted without restarting the web process.

For a separate browser-server check, I copied a stopped synthetic-only cluster from the passing run, changed the password only for its restricted reader in the copy, restored its SCRAM host rule, and started the current production B2 entrypoint with AI disabled. The app returned HTTP 200 at `/`, healthy database status, `public_interactive` state with AI disabled, the real 600-row fixed preview at zero charge, and HTTP 200 for the favicon and manifest. The copy, temporary reader secret, and quota file were stopped and removed afterward. This verifies another actual B2 HTTP runtime; it does not substitute for visual browser inspection.

These limits suit a small, supervised demonstration only. Visitor cookies are resettable and do not identify people. Before Internet exposure, add edge-level request/connection limits, abuse monitoring, and a tested provider-spend alert. Keep the one-worker/single-host quota design; do not scale replicas or place SQLite state on an unverified network filesystem.

### Local startup and HTTP smoke

From a stopped state, `start.ps1` brought up the local PostgreSQL service and launched QueryVault on `127.0.0.1:8000`. The PowerShell command returned while the recorded Python server process remained alive. The read-only HTTP smoke then passed health, access control, real counts of 600 shipments and 4 ports at zero charge, malicious-query rejection, OpenAPI, and persisted history inspection. Existing settled history reconciled to 105 cents with zero outstanding reservation; no stored query was replayed. `stop.ps1` completed graceful shutdown and the process exited. Groq and PayPal environment credentials were removed for this check.

`start.ps1` invokes the existing `setup_local.py` preflight. That local-only preflight writes a normalized `.env` from parsed settings, fills missing defaults, refreshes loopback DSNs, reapplies local schema/role setup, and analyzes the shipments table. `.env` was modified at 23:13 local time; its contents were not printed. This side effect belongs to the separate local-operator startup path; B2 did not load that file or use its database. The HTTP smoke itself ran only free read-only previews and read-only history checks.

## Browser and responsive verification — November 11 snapshot

The Windows browser-control tool was available, but its app-approval step timed out before any browser input was sent. A local browser panel was queued, but I could not inspect its rendered state. Playwright was not installed and an offline package check could not retrieve it (`ENOTCACHED`). The B2 `--browser-qa` harness also hit its 60-second PostgreSQL `initdb` timeout before app checks; a second AI-disabled attempt remained in initialization for over three minutes and was stopped. Both attempts made zero provider/payment calls, and no PostgreSQL process was left running. The successful B2 HTTP runtime and static asset checks above remain valid, but the redesigned B2 page was **not** visually inspected in a browser. No B2 screenshots, viewport clipping/touch-target results, browser console results, or browser network log are claimed. Earlier visual checks of the local operator UI at 320, 390, 768, 1024, and 1440 pixels are prior evidence and do not substitute for B2 browser QA.

## Regression, build, and evidence integrity

- Backend: **210 tests passed**, **26 subtests passed**, no failures; one existing Starlette/httpx deprecation warning.
- Frontend: **37 tests passed** across six files.
- TypeScript and production Vite build: passed.
- Current build output: initial JavaScript **283.26 kB** (**86.29 kB gzip**), CSS **30.73 kB** (**6.87 kB gzip**), lazy seller-ledger chunk **1,118.07 kB** (**315.37 kB gzip**). Vite continues to warn that the lazy chunk exceeds 500 kB. No new dependency was added.
- A scan of the built frontend found no Groq-key pattern or operator/database credential variable names.
- All **17/17** protected historical evidence files matched `.local/engineering-evidence-baseline.json`. The historical $20 authorization, $0.70 and $0.35 query charges, $1.05 final capture, zero reconciliation discrepancy/reservations, and separate $20 authorization voided with $0 capture were not re-run or rewritten. The local smoke used free read-only previews; no payment or ledger mutation was performed.

## Deployment and infrastructure status — November 11 snapshot

Merged Compose configuration validates with `QUERYVAULT_PUBLIC_ORIGIN=http://127.0.0.1:8002` and `QUERYVAULT_HOST_PORT=8002`. It selects `public_interactive`, defaults `QUERYVAULT_INTERACTIVE_ENABLED=false`, maps only `127.0.0.1:8002` to the web container, publishes no PostgreSQL host port, uses the separate `queryvault_interactive_demo` database/volume, and mounts a separate quota-state volume. Web runs non-root with a read-only filesystem, dropped capabilities, `no-new-privileges`, CPU/memory/PID limits, and one worker in the intended container configuration.

The Docker CLI client is present (28.0.1) on context `desktop-linux`, but there is no server. The Docker Desktop Linux Engine pipe `//./pipe/dockerDesktopLinuxEngine` is unavailable. No container build, secret mount, container filesystem/UID check, restart, or container SIGTERM check is claimed. The local Compose secrets directory is absent, so host ACLs/ownership for real deployment secrets have not been verified; no production secret was created for this pass.

No real HTTPS origin, reverse proxy, DNS, firewall, or hosting environment was available. Public mode keeps `proxy_headers=false`; a future proxy must preserve the canonical Host and same-origin request, and the configured public origin must be the exact HTTPS origin. Terminate TLS at a trusted proxy, keep the database private, expose the app only through that proxy, and apply edge body/time/connection/rate limits. Compose's loopback port binding is not a public ingress configuration.

Python dependencies are version-pinned but not package-hash locked, and base images are major-version tags rather than reviewed digests. Expected-load testing, Internet penetration testing, monitoring/alert delivery, host secret ACL checks, and a real volume backup/restore rehearsal remain unverified.

## Verification commands

Run the following from the repository root. B2 reports are written under ignored `.local` paths and the verifier refuses to overwrite an existing report path; choose a new report filename for a repeat run.

```powershell
.\.venv\Scripts\python.exe verify_interactive.py --mock-provider --report-file .local\optionb-final-runtime-last.json
.\.venv\Scripts\python.exe verify_interactive.py --no-live --report-file .local\optionb-final-disabled-last.json
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

SQL evaluation was run from a disposable working directory so it did not overwrite the root `evaluation.json`:

```powershell
$project = (Get-Location).Path
$eval = Join-Path $project '.local\optionb-sql-evaluation-20261111'
New-Item -ItemType Directory -Force $eval | Out-Null
Copy-Item .\holdout.json (Join-Path $eval 'holdout.json') -Force
Push-Location $eval
try { & "$project\.venv\Scripts\python.exe" "$project\evaluate.py" } finally { Pop-Location }
```

The verified local lifecycle commands are `.\start.ps1` and `.\stop.ps1`. The direct smoke command is `.\.venv\Scripts\python.exe .\verify_http.py --base-url http://127.0.0.1:8000`.

## Final gate — November 11 snapshot

At the November 11 cutoff, Option B had passed isolated application/HTTP integration but lacked a Docker runtime and visual browser inspection. The November 12 staging follow-up closed those local rehearsal gaps. Current status is **not ready for controlled public deployment yet**: a real HTTPS host/proxy, edge limits, monitoring, target-host secret/permission validation, and an explicitly approved server-side Groq setup still remain. No deployment or publication occurred; see the current [deployment gate report](DEPLOYMENT-GATE-REPORT.md).
