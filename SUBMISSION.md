# QueryVault — final local submission materials

## Devpost draft

**Tagline:** A supply-chain research agent that can buy an answer without owning SQL access or unlimited spending authority.

**Problem.** Useful enterprise data is expensive and sensitive. Giving an AI agent unrestricted database credentials or payment authority is a poor substitute for a governed buying process.

**What we built.** QueryVault lets a human approve one PayPal Sandbox research budget. The agent proposes SQL and compares deterministic quotes with its remaining budget. The gateway resolves SQL access, enforces fixed accepted prices, atomically reserves funds in PostgreSQL, executes through a restricted reader and accrues successful billable usage. One final capture settles the exact ledger total; zero spend voids the authorization. The seller sees matching quotes, charges, security rejections and independently verified settlement.

**Verified demonstration.** A USD 20 Sandbox authorization funded two queries at USD 0.70 and USD 0.35. One USD 1.05 final capture was independently retrieved as COMPLETED with zero ledger difference. A separate unused USD 20 authorization was independently VOIDED with zero capture. These are historical verified records, not transactions created for the current recording. Data is explicitly synthetic. Payment identifiers/account details are removed from public artifacts.

**Engineering.** FastAPI, React/TypeScript, PostgreSQL, SQLGlot, Groq, PayPal Orders/Payments v2 and AG Grid Community. HMAC-bound quotes, session-first row locking, a database budget invariant, single settlement claim and fenced reservation recovery keep model proposals outside the financial/security authority boundary.

**Evidence.** The final audit passed 213 backend tests and 26 subtests on Docker/Linux with isolated PostgreSQL and 38 frontend tests. TypeScript and Vite passed in a clean Docker build. The SQL evaluation executed 24/24 legitimate cases, rejected 26/26 adversarial cases, passed all 10 holdouts, and matched 20/20 known answers. The AI-disabled Option B smoke returned 600 synthetic shipments at zero charge over HTTP. Real Groq and PayPal Sandbox evidence comes from earlier runs.

**Limits.** Local single-operator prototype. Authorizations are not escrow or guaranteed payment. Payment ambiguity requires operator reconciliation. No public production deployment, load-testing claim or formal semantic-equivalence proof is included. See SECURITY.md and QA-REPORT.md.

## Final 2:40 demonstration

See [FINAL-DEMO.md](FINAL-DEMO.md) for the final second-by-second shot list, narration and recording constraints. It uses the human-readable decision timeline and completed-session panel with existing historical evidence; no new payment is needed.

## Shot assets

Buyer-workspace screenshots: assets/buyer-desktop.jpg, assets/buyer-tablet.jpg and assets/buyer-mobile.jpg. Seller screenshots remain local because they display internal ledger row and quote identifiers.

## Owner handoff checklist

- Review project name, attribution/license and Devpost text.
- Record the storyboard in under three minutes with historical labels visible.
- Review the recording for private information and narration accuracy.
- Decide repository visibility and approve any public upload separately.
- Confirm event-specific eligibility/deadline/category requirements in the submission portal.
- Publish/upload/submit only after explicit owner approval. None has been performed here.
