# 06 — Marketplace Loops

Loops are scheduled or event-triggered processes that run *over* the graphs. Each one is bounded, observable and recoverable.

## L1 — Outcome Learning Loop (FSD §35, BRD §27, Skill §36)

| Step | Implementation | Autonomy |
|---|---|---|
| Opportunity → Reported outcome + reason | `OutcomeReported` event, reason category from configurable list (FSD-OUT-001) | AL0 |
| Aggregate pattern analysis | Nightly worker job per institution × appetite version: decline reasons × criteria satisfied | AL2 |
| Compare with configured appetite | Deterministic thresholds (see G6) | AL2 |
| Detect mismatch → Insight | `appetite_insight` row with evidence counts (k ≥ 5) | AL2 |
| Narrate | AI CP `narrate_insight` from structured evidence only (no invention); fallback template | AL1 |
| Human review | I-18 queue: dismiss / simulate / draft new version | AL0 |
| New ruleset version → future matching | via appetite lifecycle + G4 | AL0 → AL2 |

**Stop:** one open insight per (appetite, rule, reason). A dismissed insight is suppressed for 30 days unless the evidence doubles.

## L2 — Product Intelligence Loop (FSD §31, Skill §37)

Weekly: cluster unmatched + near-match demand by (purpose_category, sector, amount band, region). Clusters with ≥ 20 needs or value ≥ configured threshold, where product coverage ratio < 0.3, become **Product Gap** entries, shown to institutions whose supply is adjacent (same family or sector). "Simulate hypothetical product" reuses the simulator with a synthetic product version (`synthetic=true`). **Never creates products** (`HUMAN_PRODUCT_DECISION`).

## L3 — Commercial / Billing Loop (FSD §39–40, TSD §43–46, Skill §43)

```text
OpportunityRouted → BILLING_ELIGIBILITY (contract.qualified_definition: verification level, intent, mandatory profile, match ≥ threshold, selection, consent, not duplicate within window, routed OK, not synthetic, billing kill switch off)
→ CommercialEvent (BILLABLE or INCLUDED_IN_PLAN if allowance remains) — idempotent
→ monthly statement → ACCEPTED or DISPUTED (within dispute window)
→ dispute graph → CHARGE_VALID | CHARGE_REVERSED (reversal event) | OPPORTUNITY_REPLACED (credit + link to replacement)
→ analytics: revenue/institution, revenue/opportunity, cost/opportunity (AI tokens, messages), contribution
```
Financial history is never mutated. Corrections are reversal or credit events (Skill §49).

## L4 — Marketplace Integrity Loop (FSD §38, TSD §41, Skill §42)

Signals (V1 rules, each versioned):

| Signal | Rule | Weight |
|---|---|---|
| Duplicate phone | same phone_hash has active need with same purpose_category within 30 d | high |
| Duplicate identity | same NIN hash across different phone | high |
| Velocity | > 3 needs per phone / 7 d; > 10 sessions per IP / hour | medium |
| Device reuse | same device_hash across > 3 customers / 7 d | medium |
| Partner anomaly | partner's conversion-to-consent > 3σ above network or > 30 % integrity flags | medium |
| Synthetic pattern | identical free-text intent across > 5 customers / day | medium |
| Repeated disputes | institution disputes > 25 % of events in a month (institution-side integrity) | review |

Score → NORMAL / REVIEW / HIGH_RISK / BLOCKED. REVIEW holds routing (customer told "we're completing checks") → `HUMAN_REVIEW_INTEGRITY_CASE` → ALLOW (resume saga) / BLOCK. Integrity is **never** shown as creditworthiness.

## L5 — Notification & Escalation Loop (FSD §33, TSD §34, Skill §44)

```text
Domain event → NotificationPolicy(event_type, priority rules: value, match, waiting time, service target)
→ RecipientResolution (role, team, assignment, preferences, tenant)
→ ChannelSelection (in-app always; email; SMS/WhatsApp for customers and critical; Teams/push adapters later)
→ Delivery (adapter) → status → ack if required → escalate if not acked within window → manager → WEZA Ops
```
Priority matrix per FSD §33. Digests: WEZA Daily (07:00 local) and WEZA Weekly (Mon 07:00), generated from deterministic aggregates and narrated by AI with a template fallback. Retry: 5 attempts with exponential backoff → DEAD_LETTERED → admin A-12 (replay button, idempotent).

## L6 — Freshness & Service-Target Loop
Every 5 min the worker scans `assignment.*_due_at` and `opportunity.last_activity_at` → emits Approaching/Breached and freshness transitions → L5.

## L7 — Retention Loop (TSD §70)
Nightly: evaluate (data type, purpose, consent, legal hold, policy, last activity) → RETAIN / ARCHIVE / ANONYMISE / DELETE. V1 defaults: abandoned journeys anonymised after 180 d; identity vault records with no opportunity deleted after 365 d; audit/commercial retained 7 y. Each action is audited.

## 7. Loop stop / retry / failure model (Skill §45, §61)

| Loop / agent | Max iterations | Max tool calls | Max runtime | Cost budget | On exhaustion |
|---|---|---|---|---|---|
| Intent understanding (per need) | 6 turns | 2 AI calls/turn | 20 s per AI call | 8k tokens/turn, 40k/need | Structured form mode |
| Profile questioning | 25 questions | 1 AI phrase/turn | 10 s | 20k/need | Structured questions only |
| Missing-item cycle | 3 | — | — | — | Save & exit + reminder |
| Product extraction agent | 1 doc pass + 1 repair | 4 | 120 s | 60k/doc | Manual editor with partial draft |
| Institution assistant (per question) | 4 reasoning steps | 3 tools | 30 s | 16k | "I can't answer that safely" + show raw tool result |
| Insight narration | 1 | 0 | 15 s | 4k | Template text |
| Event consumer | 5 attempts | — | 30 s each | — | Dead letter + alert |
| Clearing run | 1 per trigger | — | 60 s | — | Split scope, retry |
| Waiting room renewals | 3 | — | — | — | Expire |

Every exhaustion writes a `loop_budget_exhausted` metric and, where defined, a Human Control Centre item. **No `while True: ask_llm()` exists anywhere.** The AI Control Plane enforces budgets centrally per `(capability, subject)`.
