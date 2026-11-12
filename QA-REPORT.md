# Final engineering QA — November 9, 2026

## Result

**Ready for owner review, demo recording and permissioned publication. Not yet externally submitted.** No additional PayPal transaction was initiated during this QA pass. The existing capture/void integration was preserved.

## Verified evidence

| Area | Command/method | Actual result |
|---|---|---|
| Backend | .venv Python -m pytest -q --junitxml=test-results.xml | 110 passed + 26 subtests; one existing Starlette/httpx deprecation warning |
| Dependencies | Python -m pip check | No broken requirements |
| Frontend | npm run build; npm test | TypeScript/Vite build and 10 Vitest tests passed |
| HTTP | verify_http.py against running FastAPI | Static build, health, access control, two real SQL answers, rejection, OpenAPI and persisted settled history passed |
| Clean reproduction | reproduce.py | Actual bootstrap in copied checkout/new .venv/fresh PostgreSQL cluster; all 7 checks passed; test services stopped |
| Security corpus | evaluate.py | Preserved 24 legitimate/26 adversarial main cases plus 5/5 independent holdouts; 20 known SQL answers matched |
| Real AI baseline | Existing live-ai-evaluation.json | 3/3 correct, reported separately |
| Additional real AI | evaluate_heldout_ai.py | 12 attempted, 12 correct, 0 incorrect/model failures/policy rejections/scope stops; no retries or prompt tuning |
| Scope protection | Mock fault/behavior tests | Changed-scope declaration and changed filter structure stop before execution; broader NL equivalence remains unproven |
| UI | Real Chrome desktop, 768px tablet, 390px mobile | Both workspaces inspected; no page-level horizontal overflow; AG Grid scrolls internally |
| Interaction | Actual keyboard/browser actions | Tab moved from historical-inspector button to objective textarea; filter and empty state; malicious-query rejection, dismiss/recovery; no payment controls activated |
| Console | Browser captured warning/error logs | Empty during captured QA checks |
| Screenshots | Browser captures saved to assets | Six real JPEG screenshots, no generated screenshots |
| Privacy | Public-source scan and manual review | No configured credential values found outside private files; raw historical references removed from public artifacts; final archive scan recorded in public-audit.json |

## Verified problems fixed

1. Public evidence/docs included complete historical payment identifiers. Originals were preserved in ignored private evidence; public reports were redacted. UI receipts mask sensitive references, and the public one-off historical payment runners now refuse replay.
2. Bootstrap assumed one installed Windows PostgreSQL directory, executable suffix and port. It now discovers tools, supports PG_BIN, isolated port/cluster/env settings and platform executable selection. A cross-platform Python bootstrap is provided; actual clean verification was Windows only.
3. Empty local credential fields could survive setdefault and quoting could corrupt keys containing special characters. Empty generated fields are now filled, and dotenv values are quoted. Environment files receive restrictive modes on POSIX.
4. Local login was tied to port 8000. Same-origin login now checks the actual request origin and works in isolated port-8001 reproduction.
5. Database failures could expose unhandled/misleading service errors. Safe 503/504 responses now avoid backend details; tests cover both cases. Frame denial/no-store headers apply across the app.
6. A fresh judge checkout lacked payment history and could tempt a new test transaction. A sanitized, clearly labeled historical evidence endpoint/card now supports a useful zero-payment demonstration. Missing-credential order creation is disabled in the UI.

## Reproducibility scope

Tested: Python 3.13, Node 22, PostgreSQL 18 on Windows. Fresh dependency install, npm ci, production build, initial/repeated migrations, synthetic seed, backend startup, no-key health, free SQL preview, historical evidence and malicious query rejection. The isolated bootstrap did not use operator keys or the main cluster. PostgreSQL server tools remain a documented prerequisite. Linux/macOS behavior is implemented but unverified; Docker daemon was unavailable and no Docker test is claimed.

## Known limits / defects

- Local single-operator application; not safe to deploy as a public multi-tenant service without real identity/tenant controls and operations hardening.
- Small synthetic AI/security evaluation; no formal correctness or exhaustive-security guarantee. Extra held-out cases produced zero scope-change stops, so zero is a measured count, not proof of semantic safety.
- Unknown provider outcomes require reconciliation/operator investigation. No automatic payment replay, webhook consumer or background recovery sweeper.
- AG Grid remains a roughly 1.12MB lazy chunk and triggers Vite's size warning. Buyer initial JS is about 246KB uncompressed.
- One installed Starlette/httpx deprecation warning remains; tests pass. It is not silently suppressed.
- A full-page browser screenshot request timed out once. The documented normal viewport capture succeeded; six real screenshots were saved.
- No demo video was recorded and no event portal submission, public push or deployment was performed.

## Next owner actions

Review the sanitized source archive and materials; record/review the 2:50 storyboard; approve publication/upload; confirm event-specific portal requirements and submit. Another PayPal transaction is unnecessary for the prepared historical-evidence recording.

## Presentation-only follow-up

110 backend tests + 26 subtests and actual HTTP checks passed again. Frontend tests increased to 10, all passing; production build passed. Browser verified the human-readable timeline with real recorded $0.70/$20 budget facts, zero terminal-session settlement controls, collapsed new-checkout controls, historical evidence without an active live session, responsive views and zero captured warnings/errors. Refreshed screenshots retain explicit saved/historical labels. “Unspent session budget” is accounting only, without a funding-hold release claim. No new transaction or architectural change. Final recording instructions are in FINAL-DEMO.md.

## Economic-decision follow-up

115 backend tests + 26 subtests, 10 frontend tests, production build and HTTP smoke checks passed. Real non-billing evaluation yielded two 70-cent quotes against 50 cents available, for one unchanged normalized plan; three model responses ended in refusal, with no agent SQL execution. No successful optimization or distinct cheaper rewrite is claimed. Initial one-quote refusal probes were preserved. A separate fresh SQL query returned 600 through actual HTTP and browser preview at zero query fee. Existing PayPal evidence was not replayed or mutated. The adjusted run saved its complete real report before a Windows console rendering error; UTF-8-safe rendering was fixed and verified against the saved report. All evidence/mode distinctions and the 2:40 storyboard are in ECONOMIC-DEMO.md and FINAL-DEMO.md.
