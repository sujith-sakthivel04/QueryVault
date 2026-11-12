# Real non-billing economic-decision demonstration

## Audit finding

The existing research loop already compares each backend quote with remaining budget and asks for a cheaper same-scope plan. It stops after three proposals and has a conservative structural scope guard. The missing proof was a real constrained-budget run: the earlier paid $0.70-vs-$20 example established affordability, not difficult economic choice.

This pass adds structured attempt evidence and one bounded reconsideration step when an over-budget model response supplies no alternative SQL. It asks the model for a same-scope rewrite or an honestly unchanged requote; it supplies no SQL, price or required successful outcome. The three-attempt limit and scope guards remain. Initial scope-change responses without prior over-budget quotes still stop for review. No architecture or UI was changed.

## Actual observed outcome

Frozen objective: port-level average delay, rounded to two decimals, over the **entire October 2026**, ordered by port name.

| Observation | Actual value |
|---|---|
| Evaluation allowance | 50 cents, explicitly separate from PayPal |
| First real quote | 70 cents, PostgreSQL planner cost 64.4 |
| Next model response | No alternative SQL proposed |
| Bounded reconsideration | Model returned the original full-scope SQL for a fresh quote |
| Second real quote | 70 cents, planner cost 64.4 |
| Distinct normalized quoted plans | 1 |
| Observed price reduction | 0 cents |
| Final decision | Refused after three model responses |
| Agent SQL executions | 0 |
| Financial sessions / PayPal calls / query fees | 0 / 0 / 0 |

**This is a genuine budget refusal and unchanged-plan requote. It is not a successful optimization, and no distinct cheaper rewrite was observed.** The model's assertion that nothing cheaper is possible is not accepted as a proof. The demonstrated claim is only that it found no affordable validated alternative within its limit and did not spend anyway.

Earlier probes are retained locally and are not hidden or substituted with a scripted success. The unadjusted loop stopped after one quote/refusal. The adjusted run's API/SQL work and report saving completed, but Windows console encoding failed on a model-generated Unicode character; the UTF-8-safe renderer was fixed and verified against the saved report without replaying a model call. Raw provider and run artifacts are intentionally omitted from the public source candidate; this narrative preserves the verified outcome and limitation.

## Reproduce a new real non-billing run

```powershell
.\.venv\Scripts\python demo_economics.py --budget-cents 50
```

Requires configured Groq access and PostgreSQL. Provider token usage still applies. Non-billing means no QueryVault query fee or PayPal operation. The adapter calls the existing SQLGlot policy, real restricted-reader EXPLAIN and production price_plan function. It creates only ephemeral evaluation quote IDs and an explicit evaluation allowance; it does not fabricate an authorized financial session, mint a commercial payment quote, or write a financial ledger.

Outputs may vary with model/service/planner state. Do not promise the recorded numbers or a successful optimization. The report saves actual proposals, reasons, quotes, SQL hashes, scope stops/refusals and any execution/reference comparison.

The sanitized outcome is described above and in [FINAL-DEMO.md](FINAL-DEMO.md). Raw reports and provider text are retained locally and excluded from the public source candidate. There is no command to replay or print the raw historical report. The command above performs fresh inference and should only be run with the operator's own Groq key and explicit consent.

## Fresh useful functionality — separate from optimization

The actual demo run also executed a separate free count returning 600 October shipments. A fresh request through the running /demo/query endpoint independently returned 600 at zero query fee. Browser QA executed another fresh preview using this SQL:

```sql
SELECT COUNT(*) AS fresh_october_shipments
FROM shipments
WHERE shipped_on BETWEEN '2026-10-01' AND '2026-10-31'
```

Use **Free synthetic preview** in the existing buyer workbench. It returns one aggregate result row containing 600, labeled a free preview with query charge $0.00. This is not a substitute or cheaper equivalent for the original port-delay question; it is a separate live functionality check. The screenshot and raw report remain local; see FINAL-DEMO.md for the reviewed demo plan.

## Payment distinction

The USD 1.05 PayPal Sandbox settlement remains separately labeled historical evidence, funded by an earlier USD 20 human-approved session. Today's 50-cent evaluation allowance is not that payment budget. No payment records were replayed or additional Sandbox transactions initiated. FINAL-DEMO.md keeps these two stories distinct.
