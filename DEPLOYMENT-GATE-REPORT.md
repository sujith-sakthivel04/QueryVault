# QueryVault deployment gate

**Updated decision (November 12, 2026): NOT READY for controlled public deployment yet.** The Docker/Linux staging gate and real browser workflow now pass, including the corrected production frontend. Public TLS, edge controls, monitoring, production-host secret validation, and an owner-approved server-side Groq setup remain. No public deployment was performed.

## Ready

- Public interactive mode keeps operator, seller, SQL-admin, financial, and PayPal routes unavailable.
- The new frontend build is served by the real B2 application; the accepted workflow produced a real 600-shipment count at a deterministic 35-cent virtual quote.
- SQL firewall, exact quote/hash acceptance, idempotency, quota ceilings, AI kill switch, read-only fallback, restart persistence, database outage/recovery, and isolated backup/restore checks passed.
- AI is disabled by default. The public application has no payment authority. The November 11 evidence-baseline check found all 17 protected files unchanged; this staging pass did not modify those files.
- Compose configuration validates with a loopback-only web port, no database host port, a distinct B2 database/volume, and a distinct quota volume.

## Docker/Linux staging rehearsal — November 12, 2026

The Docker Desktop Linux Engine was reachable on context `desktop-linux`: Docker client/server **28.0.1**, Linux `amd64`; Docker Compose **2.33.1**. The real multi-stage `Dockerfile` built the web, migration, and quota-init images. Node 22 and Python 3.13 build stages completed; TypeScript and Vite passed. Image tags were `qv-b2-stage-20261112-7a2c-web` (`b756fbba3004`, 186 MB), `...-migrate` (`369f3de93d06`, 186 MB), and `...-quota-init` (`50616d2fa97b`, 186 MB). PostgreSQL was `postgres:18-bookworm` (`107127087bab`, 440 MB). Vite retains its existing 1,118.07 kB lazy seller-ledger chunk warning.

The test used the new Compose project `qv-b2-stage-20261112-7a2c`, synthetic-only database `queryvault_interactive_demo`, temporary random passwords and a fake provider-key sentinel under `.local/qv-b2-stage-20261112-7a2c`. The final web port was `127.0.0.1:18123`; PostgreSQL had no host port. The app initially ran with `QUERYVAULT_INTERACTIVE_ENABLED=false`; `/api/config` reported `public_interactive`, `live_ai=false`, `interactive_ai=false`, `operator_workflows=false`, and `payments=false`. No PayPal or Groq request was made. For browser workflow tests only, a staging-only Python entrypoint replaced `interactive_api.propose` with a deterministic in-process mock. It did not call Groq.

| Check | Actual result |
|---|---|
| Fresh Compose start and dependencies | PostgreSQL healthy; migration exited 0; web healthy. Repeat migration succeeded. Re-running quota initialization reported existing state and did not reset it. |
| HTTP and frontend | HTTP 200 for `/health/live`, `/health/ready`, `/`, `/favicon.svg`, `/site.webmanifest`, and `/research`. The actual production frontend build was served by B2. |
| PostgreSQL isolation | `queryvault_interactive_demo` contained 600 synthetic shipments, 4 ports, and 3 routes; zero public base tables. No operator, financial, or payment records were created. The reader was `qv_interactive_reader`, non-superuser and without database/role creation, replication, or bypass-RLS rights; it had schema usage and SELECT, but not CREATE or INSERT. A live app connection reported `transaction_read_only=on` and `search_path=vault_data, pg_catalog`. |
| Web filesystem and identity | Web ran as UID/GID `10001:10001`, with read-only root filesystem, all capabilities dropped, `no-new-privileges`, and configured resource limits. Writing under `/app` failed; `/tmp` and the quota volume were writable. |
| Secret scope and mounts | After tightening the B2 overlay, web mounted only `interactive_reader_database_url` and `groq_api_key`; migration mounted only `postgres_password` and `interactive_reader_password`. All mounts were read-only. Web could read them and could not write to the mount. The Windows host ACLs showed only the current user, SYSTEM, and Administrators; no broad Users/Everyone grant. Docker Desktop represented bind-mount mode metadata as `0777`, so the actual owner/mode and UID mapping still need verification on the target Linux host. |
| Restart and persistence | A staging-only nonzero process exit restarted web automatically (`restartCount=1`); health and HTTP returned 200. A PostgreSQL restart returned healthy with 600 shipments and web readiness 200. The anonymous wallet and completed result persisted: $0.35 virtual spend, $0 reserved, and the 600 result. |
| Backup and restore | A 9,317-byte custom-format PostgreSQL dump restored into a new temporary database and reproduced 600 shipments, 4 ports, and 3 routes. The 73,728-byte SQLite backup passed integrity and `DemoQuotaStore.validate()` after restore, preserving one wallet with 35 cents spent, no reservation, and one completed plan. The temporary restore database and quota copies were removed; the host backup files remain in the staging folder. |
| Graceful shutdown | The final `python serve.py` web container stopped within the 20-second grace period. Logs showed `Shutting down`, `Application shutdown complete`, and `Finished server process`; the container exited on SIGTERM. The loopback listener and HTTP service were then unavailable. All staging containers are stopped. The two staging volumes remain intact; no volume belonging to another project was removed. |

Docker Desktop's internal-only bridge did not publish the host port, so the temporary `.local` staging overlay uses a separate Compose bridge network with the service still bound to loopback and PostgreSQL unpublished. The bridge permits outbound networking; provider calls were prevented by the in-process mock and no real provider credentials were present. For a public host, apply explicit outbound policy appropriate to the approved Groq setup. The production Compose files were not changed for this networking workaround.

The real browser opened `http://127.0.0.1:18123`. With AI disabled, the guest could use the fixed preview and receive an actual 600-row-count PostgreSQL result at zero cost; examples did not auto-submit. With the fake provider enabled, the question produced canonical, firewall-approved SQL and a $0.35 virtual quote. The browser displayed that SQL and hash, required explicit checkbox acceptance, then executed the accepted query and displayed 600. Proof Engine showed recorded stages through result. An unsupported logistics question stopped without a quote/result; an unsafe mocked SQL proposal was rejected by the SQL firewall before quote/execution. Browser console errors: none. Viewports **320×780, 390×844, 768×900, 1024×900, and 1440×900** had no horizontal overflow.

Browser testing exposed and fixed one actual UI bug: execution returns a firewall status beginning `passed again`, but the UI previously rendered the associated detail as a rejection. The UI now treats all `passed…` statuses as passes and distinguishes a firewall that was not run. A regression test was added; the targeted frontend suite passed **16/16**, and the final Docker frontend build passed TypeScript and Vite. No payment, SQL-business, AI-provider, or historical-evidence logic was changed.

The final B2 Compose overlay also uses Compose's `!override` for the service secret allowlists. Runtime inspection confirmed that the B2 web/migration containers no longer inherit the unused B1 reader URL/password mounts. This requires Docker Compose **2.24.4 or newer**; the rehearsal used 2.33.1.

## Conditions before deployment

1. The Docker build, staging runtime, mounts, restart, shutdown, backup/restore, and B2 browser checks passed on Docker Desktop. Repeat the host-secret ownership/mode, persistence, network isolation, restart, and SIGTERM checks on the actual approved Linux host; Docker Desktop's Windows-backed file metadata is not a substitute.
2. Configure a real HTTPS origin, DNS, certificate, and trusted reverse proxy. Keep PostgreSQL private and expose web only through the TLS proxy. Preserve the canonical Host and same-origin checks; Uvicorn's forwarded-header trust remains disabled.
3. Add edge request, connection, body-size, and rate limits plus abuse monitoring and alerts. Anonymous cookies can be reset and are not strong identity. Keep one worker/host while quotas use SQLite; do not scale replicas or put SQLite on an unverified shared filesystem.
4. Install the approved Groq key only as a server-side secret, set a provider-spend alert/budget, and make a controlled provider test only after approval. The tested provider was a local deterministic mock; real Groq availability and live spend were deliberately not tested.
5. Configure monitoring/alert delivery, off-host encrypted backup retention, and expected-load limits; confirm the existing host image/dependency pinning approach. Rehearse the restore on the selected host and run a final real-browser smoke through the HTTPS proxy.
6. Obtain explicit approval for the target, domain, budget, provider-secret installation, edge controls, and the actual deployment. No deployment, publication, GitHub push, payment, or Groq call occurred in this pass.

## Keep disabled and protect

- Do not expose the local operator mode, operator `.env`, seller ledger, PayPal credentials/routes, or the PostgreSQL port.
- Keep `QUERYVAULT_INTERACTIVE_ENABLED=false` until the safeguards and owner approval are in place. Public interactive mode has no real payment path; its allowance is virtual only.
- Keep the `interactive_state` volume durable and private. Do not reset/delete it as a routine restart; it contains global/lifetime quota accounting. Do not scale replicas or use an unverified shared filesystem.
- Use a canonical HTTPS `QUERYVAULT_PUBLIC_ORIGIN`; keep the application reachable only through the TLS-terminating proxy, with the backend host port otherwise private.

## Rollback / immediate disable

For an incident after deployment, first remove the B2 route at the edge. Set `QUERYVAULT_INTERACTIVE_ENABLED=false` and create the `AI_DISABLED` marker in the existing quota volume to stop inference; retain PostgreSQL and quota volumes for investigation and recovery. Stop/restart the web service through the host's normal supervisor. If reverting to B1, use its separate `public_demo` configuration and database volume. Do not delete volumes or alter historical financial evidence as a rollback step.

## Precise next deployment steps — not executed

1. Choose an owner-approved Linux host, domain, region, monthly budget, and TLS/proxy design. Install Docker Compose **2.24.4+**. Keep the rehearsal project and its `qv-b2-stage-20261112-7a2c_*` volumes separate from any new deployment project.
2. Prepare a fresh deployment environment and review it before startup. Copy `.env.deploy.example` to `.env.deploy`, set the exact `https://<approved-domain>` public origin and loopback web port, then generate a new secret set with `prepare_deployment.py` followed by `prepare_deployment.py --interactive`. Both commands refuse to overwrite existing files. Store the real Groq key only in the approved secret store/file; do not put it in `.env`, logs, or browser code. Check Linux directory/file ownership and read access for UID 10001 without printing values.
3. Validate and build the fresh B2 configuration with AI off:

   ```powershell
   docker compose --env-file .env.deploy -p queryvault-b2 -f compose.yaml -f compose.interactive.yaml config --quiet
   docker compose --env-file .env.deploy -p queryvault-b2 -f compose.yaml -f compose.interactive.yaml build web migrate quota-init
   docker compose --env-file .env.deploy -p queryvault-b2 -f compose.yaml -f compose.interactive.yaml --profile initialize run --rm quota-init
   docker compose --env-file .env.deploy -p queryvault-b2 -f compose.yaml -f compose.interactive.yaml up -d db migrate web
   docker compose --env-file .env.deploy -p queryvault-b2 -f compose.yaml -f compose.interactive.yaml ps
   ```

   Keep `QUERYVAULT_INTERACTIVE_ENABLED=false`; verify the B2-only secret mounts, loopback/proxy reachability, no PostgreSQL host port, `/health/ready`, and public config before routing any traffic.
4. Apply the TLS proxy and edge limits/monitoring. Confirm the proxy preserves the canonical Host and same-origin behavior, PostgreSQL is unreachable from public ingress, and outbound requests are limited to approved destinations. Test alerting and the off-host restore path.
5. Only after those checks and separate owner approval, enable interactive AI for a short controlled window, run one bounded guest research question through the HTTPS browser, inspect the proposal/quote/acceptance/result and spend alerts, then disable it if any check fails. Do not configure PayPal; public-interactive mode has no payment path.

The staging startup used the same project overlays, with a disposable local secrets file and `QUERYVAULT_INTERACTIVE_ENABLED=false`; the deterministic fake-provider override was used only for browser acceptance/refusal checks. No staging container remains running. The actual runtime artifacts are under `.local/qv-b2-stage-20261112-7a2c`; keep them separate from any production secret or data path.

Detailed evidence and reproducible commands: [OPTION-B-FINAL-VERIFICATION.md](OPTION-B-FINAL-VERIFICATION.md).
