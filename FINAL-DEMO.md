# QueryVault — final 2:40 demonstration

**Target: 160 seconds (2:40), with a 20-second margin below three minutes.** Preserve the existing UI. The video has three explicitly separate sources: real non-billing economic evaluation, a fresh free database query, and historical verified PayPal Sandbox settlement. No new payment is needed.

## Preparation and truth labels

Keep New Sandbox checkout collapsed. Select the existing settled session for historical payment/ledger shots. Keep technical details collapsed unless briefly inspected. Never show credentials, account data or full transaction identifiers.

For the economic shot, use the sanitized narrative in ECONOMIC-DEMO.md and label it **recorded real non-billing evaluation**. The raw report and provider text remain local. The recorded outcome is refusal, not successful optimization: two $0.70 quotes for the same plan against a $0.50 evaluation allowance. Do not replay inference for the recording unless separately approved; if a fresh run is later chosen, show its actual outcome without forcing the saved values.

## Exact shot list and narration

| Time | Shot/action | Narration |
|---|---|---|
| **0:00–0:15** | Buyer research brief and synthetic-data label | “QueryVault helps an agent buy useful logistics answers while deterministic code controls SQL access and spending. This synthetic October dataset lets us verify both results and financial decisions.” |
| **0:15–0:55** | Show the sanitized recorded outcome from ECONOMIC-DEMO.md: 70 > 50, no distinct alternative, unchanged 70-cent requote and refusal | “Here is a recorded non-billing evaluation with a fifty-cent allowance. The first quote was seventy cents. Asked for a cheaper equivalent, the agent supplied no distinct rewrite. A fresh quote for its unchanged full-month plan was still seventy cents. It refused instead of overspending. This is verified budget discipline, not a claimed optimization success.” |
| **0:55–1:20** | Buyer workbench: paste the fresh count SQL below, click Free synthetic preview, show fresh_october_shipments = 600 and $0.00 charge | “Now we execute a separate fresh query through the running gateway. PostgreSQL returns six hundred October shipments, with no query fee. This is a functionality check—not a cheaper substitute for the original port-delay question.” |
| **1:20–1:35** | Load security test → Free synthetic preview → show rejection; dismiss | “A fresh server-file request is rejected before execution. The policy is backed by a restricted read-only database connection. The agent never receives database or payment authority.” |
| **1:35–2:00** | Historical evidence card → Inspect historical agent analysis → Session settled / saved verification | “Separately, a human previously approved a twenty-dollar PayPal Sandbox research budget. Two earlier queries cost seventy and thirty-five cents. One final dollar-and-five-cent capture was independently confirmed. These are historical verified records, not today's evaluation allowance or a new payment.” |
| **2:00–2:25** | Seller: filter charged; show 70/35-cent entries and exact $1.05 reconciliation | “The seller's accepted quotes match the recorded charges. The capture matches the ledger with zero difference. Concurrent reservations are bounded, settlement is claimed once, and uncertain payment outcomes fail closed.” |
| **2:25–2:40** | End on buyer result/settled record and brief verification context | “The safety suite covers approval, SQL boundaries and refusal behavior. This demo shows a working synthetic query, blocked unsafe SQL and separately verified historical settlement. QueryVault keeps research useful and financial claims accountable.” |

**Total: 2:40.** Do not cut the non-billing or historical labels to save time. If necessary shorten the technical-details shot or use a clearly labeled recorded real-run report. No claim that a cheaper plan was found belongs in this video.

## SQL for the fresh successful shot

```sql
SELECT COUNT(*) AS fresh_october_shipments
FROM shipments
WHERE shipped_on BETWEEN '2026-10-01' AND '2026-10-31'
```

Click **Free synthetic preview**, not the paid quote/execute controls. Expected verified result: one row, fresh_october_shipments = 600, query charge $0.00. The loading/result transition demonstrates a fresh request. Do not present this count as an optimization of the port-level average-delay objective.

## Commands

```powershell
# New real Groq + PostgreSQL evaluation; no PayPal/session/query charges
.\.venv\Scripts\python demo_economics.py --budget-cents 50

```

Live runs use Groq provider quota/token usage. SQL references are not supplied to the model. No predefined successful rewrite, artificial lower quote or altered timeframe is used. The evaluation broker is read-only/non-financial and reuses production validation/planning/pricing.

## Financial wording

Keep the $1.05 settlement explicitly historical. “Unspent session budget” is internal arithmetic, not proof of a released bank/PayPal funding hold. No new checkout, authorization, capture, void, financial-session creation or historical payment replay is part of this recording. A proposal is not an executed query; the refused agent query is not presented as executed.

The video itself is not yet recorded or published. Owner review/publication permission remains required. Detailed findings and limitations: ECONOMIC-DEMO.md.
