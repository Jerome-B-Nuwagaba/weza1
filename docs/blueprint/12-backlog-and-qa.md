# 12 — Prioritised Backlog & Acceptance-Test Plan

## 1. Implementation backlog (in build order; Skill §65)

Each item is "done" only when it meets Skill §72: UI states, backend, validation, permissions, tenant isolation, consent, audit, telemetry, unit and integration tests, and a traceability update.

### Phase 0 — Foundation
1. Monorepo scaffold, CI (lint, type-check, tests, security scans, Flutter build), pre-commit, import-linter domain contracts.
2. Platform: config, DB session, Alembic, UUIDv7, error contract, correlation ID, redacted JSON logging, rate limiter, idempotency middleware.
3. Outbox / inbox / dispatcher / dead letter / replay; graph runtime (instances, transitions, timers, interrupts).
4. Trust: audit (append-only trigger), decision ledger, classification registry, PDP skeleton.
5. Identity: vault encryption + blind index, WEZA/institution users, argon2, TOTP MFA, JWT + refresh rotation.
6. Country configuration (Uganda seed), feature flags, kill switches.
7. Web shell + design tokens + component library; Flutter shell + theme.

### Phase 1 — Customer demand
8. Journey API + G1 graph (intent → confirm → OTP → profile).
9. AI Control Plane + Anthropic adapter + deterministic fallback parser; schemas.
10. Question paths (Salaried / SME / Agriculture) + facts with provenance + conflict detection.
11. Web conversation, OTP, profile review, documents (pipeline + basic scanner).
12. WhatsApp gateway (canonical contract, signature verification) + simulator.

### Phase 2 — Institution supply
13. Join WEZA → admin verification → workspace → users/roles.
14. Product Studio with versions + maker-checker + AI extraction drafts.
15. Appetite Studio with versions + capacity + simulator + sandbox.
16. Routing rules, service targets, notification prefs, activation checklist (G2).

### Phase 3 — Matching & consent
17. Rules engine (operators: eq, in, gte, lte, between, exists), eligibility results with reason codes.
18. Match engine (components, weights config), readiness, quality score, ranking, explanation.
19. Market clearing (G4) event-driven + invalidation.
20. Customer match results, detail, preferences, consent (templates, versions).

### Phase 4 — Opportunities
21. Qualify saga (G3) with integrity/duplicate checks + compensation.
22. Disclosure Gateway + Opportunity 360 + document streaming.
23. Feed, My Day, assignment (rules + manual), unassigned queue.

### Phase 5 — Operate
24. Notifications (in-app, email adapter, SMS/WhatsApp adapters stubbed) + escalation + digests.
25. Outcome reporting, freshness loop, customer status tracker, withdrawal.
26. Manager view, Command Centre briefing, reports/export.
27. Admin Network Control Centre, Human Control Centre, Graph Inspector, audit views, kill switches.

### Phase 6 — Commercial
28. Contracts, billing eligibility, commercial events, statements, disputes, unit economics.

### Phase 7 — Intelligence (simplified)
29. Waiting Room (G5), institution mandate waiting.
30. Radius / no-lead, demand intelligence (k-anon), outcome insights (L1), rescue (G7).

### Phase 8 — Advanced (simplified, flagged)
31. Previews + interest, product gap board (L2), conversational institutional AI (tools), shadow matching.

### Delivery
32. Flutter customer app feature-complete against the API; APK built in CI.
33. Seed demo data (3 fictional institutions, ~120 synthetic-but-production-partition demo customers clearly marked DEMO), demo logins, walkthrough script.
34. Render + Vercel deployment, smoke tests against the live URL.

## 2. Acceptance-test plan

**Layers:** unit (pytest, vitest) · graph tests (node/edge/branch/invalid/interrupt/timeout/retry/idempotency/compensation/migration/human) · API integration (pytest + real Postgres in CI) · security tests · end-to-end (Playwright on web) · Flutter widget tests · manual exploratory QA on the deployed URL.

| ID | Scenario | Expected |
|---|---|---|
| AT-01 | Start via `/?src=qr&cmp=Q4SME` | attribution persisted through to commercial event |
| AT-02 | Same journey via WhatsApp simulator | identical graph states and outcome |
| AT-03 | "I need UGX 30 million to expand my pharmacy" | amount=30,000,000 UGX, purpose=expansion, type=SME, sector=health/pharmacy |
| AT-04 | "I need money for school fees" | purpose=school fees, amount missing → asks amount only |
| AT-05 | Confirmed fact not re-asked; SME vs Salaried path differ | asked_keys unique; correct question sets |
| AT-06…09 | OTP wrong / expired / max attempts / resend limit | correct errors; lockout; no plaintext OTP in DB or logs |
| AT-10 | Correct profile after matching | matches INVALIDATED and recomputed |
| AT-11 | Upload EICAR / wrong type / >10 MB | rejected, never sent to AI |
| AT-12 | Readiness states | READY_NOW / ALMOST_READY (missing doc) / NO_CURRENT_MATCH |
| AT-13 | Paused product / FULL capacity / suspended institution | excluded from matches |
| AT-14 | Appetite change | clearing run re-matches affected needs only |
| AT-15 | Match explanation | every reason maps to a rule code; "not an approval" label present |
| AT-16 | Preference change | order changes, eligible set doesn't |
| AT-17 | Consent | record has template version + text hash + categories |
| AT-18 | Withdraw consent | identifiable fields hidden on new views; event logged |
| AT-19 | Opportunity snapshot | contains profile snapshot id, product/appetite versions, scores, attribution |
| AT-20 | Double-submit consent (same idempotency key / replayed event ×3) | 1 opportunity, 1 routing, 1 billable event |
| AT-21 | Product paused between selection and consent | no disclosure; customer re-matched (FSD-OPP-005) |
| AT-22…28 | Institution join → verify → products (maker-checker) → appetite (simulate required) → routing → activate | activation blocked until all checks pass |
| AT-29 | Command Centre per role | officer vs exec cards differ; briefing numbers match DB |
| AT-30 | Feed ranking explainer | factors shown |
| AT-31 | Preview payload | contains no name/phone/NIN/email/address/district when k<5 |
| AT-32…33 | Auto-assign by rule; no rule → Unassigned + manager alert; target breach → escalation | as specified |
| AT-34 | Report Approved 25M, Disbursed 25M | labels "Reported by …"; analytics + commercial updated |
| AT-35 | Empty queue | Radius near-miss intelligence shown |
| AT-36 | Waiting room: new appetite activated | customer notified, no disclosure |
| AT-37 | Demand analytics | cells < 5 suppressed |
| AT-38 | "Show my best SME opportunities today" | tool call scoped to tenant; answer cites results |
| AT-39 | High value + high match | priority alert to the right role |
| AT-40 | 10+ declines on enforced turnover rule | insight created; appetite unchanged |
| AT-41 | Decline → alternatives → new institution | new consent required; previous data not shared |
| AT-42 | No activity 8 days | STALE + reconfirmation |
| AT-43 | Same phone, same purpose twice in 30 d | duplicate hold; no double billing |
| AT-44…46 | Billing within allowance / beyond; dispute → reversal event | ledger correct, never mutated |
| AT-47, 50 | Kill switch pause institution | removed from options; re-clearing; audited w/ reason |
| AT-48 | Audit for every listed FSD §42 action | rows exist; UPDATE/DELETE blocked |
| AT-49 | Zero-integration | no outbound institution connector exists (static test); copy states boundary |
| AT-51 | Decision ledger | reconstruct "what WEZA knew" for an opportunity |
| AT-52 | Second country config (e.g. KE test) | works without code change |
| AT-53 | Sandbox | synthetic data never billed or visible in production feed |
| AT-54 | AI UNAVAILABLE | full journey completes via structured mode |
| AT-SEC-01 | Institution A requests B's opportunity id | 404 (no existence leak), logged |
| AT-SEC-02 | Officer reads unassigned opportunity identifiable data | DENY / restricted |
| AT-SEC-03 | Disclosure before consent via any endpoint | impossible |
| AT-SEC-04 | Prompt injection in customer text / product doc | no tool misuse, schema-valid output |
| AT-SEC-05 | Rate limits on OTP/login | 429 with retry-after |
| AT-SEC-06 | Logs | no phone/NIN/OTP values |
| AT-GR-01…08 | Graph runtime: node, edge, invalid transition, interrupt/resume, timeout, retry→FAILED, idempotent resume, version migration | pass |
| AT-API-01 | Error contract on 400/401/403/404/409/422/429/500 | standard shape + correlation id |
| **E2E-01** | **FSD §53 full scenario** (pharmacy UGX 30M → Institution B → assign → contact → Reported Approved → Reported Disbursed UGX 25M → billing + analytics) | passes in Playwright against a deployed environment |
