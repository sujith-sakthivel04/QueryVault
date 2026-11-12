# Security model and disclosure notes

QueryVault is a loopback-only, single-operator hackathon prototype. Do not expose the current app publicly as a multi-user service. Report suspected vulnerabilities privately to the repository owner; do not post credentials or raw financial evidence in public issues.

## Boundaries

The model receives schema and research intent, not PayPal/database credentials. It proposes SQL; it does not decide grants, prices, reservations or capture. SQLGlot checks a strict supported subset and resolves allowed tables/columns. The reader connection independently repeats validation and planning checks. PostgreSQL roles and transaction/time/resource limits remain essential even if parser policy fails.

The data schema contains only labeled synthetic logistics records. Reader grants exclude application sessions/quotes/ledger. PostgreSQL system catalogs retain built-in visibility; gateway catalog queries are rejected. We do not claim complete catalog invisibility.

Quotes bind owner/session, SQL hash, fixed cents, policy/price version and expiry using HMAC. Execution checks the accepted ceiling, hash, current policy and signature under session-first locks. Ledger entries are append-only to the app role and protected by an update/delete trigger; a database administrator remains trusted. Reservations, completion, settlement drain and recovery use the same lock order. Fenced late workers cannot charge or deliver recovered results.

## Payment safety

Only Sandbox is accepted. Mutation request IDs are persisted before provider operations. Unknown results are not automatically retried or replaced by another payment. Independently retrieved capture status/amount must match the charged ledger. Pending/mismatched outcomes close admission for reconciliation. A confirmed authorization is not completed payment or escrow; merchant pre-capture risk is bounded by the session budget.

PayPal errors preserve raw diagnostics for local operator troubleshooting. Treat terminal/log output as private. Public artifacts remove payment/account references; raw evidence and credentials are ignored/excluded. The source archive is allowlisted and scanned for configured secrets and known historical references before creation. This scan is a focused safeguard, not proof that every possible secret pattern has been detected.

## Local browser surface

Trusted Host checks, same-origin writes, cross-site write rejection, HttpOnly SameSite cookies, no-store caching and frame denial protect the local app. Local login trusts the single local operator and is not an Internet authentication system. Return/cancel pages do not trust callback flags as approval and never perform payment mutations. Reader/provider failures return safe, actionable HTTP errors without backend connection details.

## Explicit residual risks

Model-generated semantics can be wrong despite a valid safe query. Structural scope checks are conservative and are not a formal proof. Synthetic evaluation is small. No penetration-test/exhaustive-security or throughput claim is made. Payment recovery remains operator-assisted; no distributed commit with PayPal is possible. Public deployment would require real identity/tenant authorization, operational secrets management, monitoring, abuse/rate controls, recovery/webhook design and broader testing.
