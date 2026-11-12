# What QueryVault contributes

QueryVault is an application-level data-commerce demonstration: **which SQL may run, what exact price was accepted, how concurrent queries share a budget, and how that ledger reconciles with one final payment.** It is not a new payment rail or a claim to be the first agent-payment product.

| Existing approach | Its documented focus | QueryVault's implemented focus |
|---|---|---|
| Conventional pay-per-API endpoint | Meter/authorize access to an API operation | A policy-checked SQL plan receives a binding quote, atomic reservation, result policy and auditable charge |
| x402 | HTTP resource/payment handshake using payment-required/signature/response headers | QueryVault currently uses PayPal Sandbox session authorization/final settlement; it does not implement x402 |
| AP2 | Securing agent-performed transactions through verifiable intent/checkout/payment mandates | QueryVault implements a concrete budgeted database workflow and deterministic SQL/money boundaries; it does not claim AP2 compatibility |
| Payment/agent toolkits | Expose commerce/payment capabilities to applications and agents | QueryVault composes real provider APIs with SQL security, concurrency, quoting and seller reconciliation |

This is a difference in demonstrated enforcement surface, not evidence that the other projects cannot support similar designs. There is no novelty, market-leadership or broad competitor-performance claim.

Primary references checked November 9, 2026: [x402 HTTP transport specification](https://github.com/x402-foundation/x402/blob/main/specs/transports-v2/http.md), [AP2 specification](https://ap2-protocol.org/ap2/specification/), [PayPal AI Toolkit commerce guidance](https://github.com/paypal/AI-Toolkit/blob/main/skills/paypal-best-practices/references/agentic-commerce.md).
