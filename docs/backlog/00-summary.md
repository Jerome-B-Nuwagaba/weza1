# WEZA Backlog Summary

## Executive Summary

Read-only analysis completed. The codebase is significantly implemented, with backend tests passing (`68 passed, 3 xfailed`; xfails are WhatsApp-specific and excluded). The main release risk is not missing core marketplace functionality; it is uneven control/test coverage around production hardening: idempotency, rate limiting, retention, observability, accessibility, schema/doc alignment and parallel migration discipline.

Completion estimate method: I counted each in-scope requirement in `02-traceability-matrix.md` as Done = 1.0, Implemented weakly tested = 0.75, Partial = 0.5, Missing = 0.0, Deferred/excluded removed from denominator.

| Domain | Honest completion | Basis |
|---|---:|---|
| Platform/db/outbox/graph | 78% | Graph/outbox implemented and tested; observability, inbox doc mismatch, Alembic CI gaps remain. |
| Identity/trust/security | 80% | Vault/RBAC/OTP/audit strong; retention, classification and broad rate limits incomplete. |
| Customer/need/journey | 85% | Main journey tested; document and preference edge coverage thin. |
| Institution/product/appetite | 86% | Onboarding/product/appetite flows tested; extraction edge tests needed. |
| Matching/opportunity/consent | 88% | Core E2E, consent, idempotent replay pass; integrity/waiting room edges need work. |
| Notification excluding channels | 60% | In-app/email/escalation exist; digests and channel-adjacent policy gaps remain. |
| Commercial/integrity | 76% | Billing/dispute tested; integrity patterns thin. |
| Intelligence/admin | 72% | Tool assistant/insights exist; endpoint coverage and AI provider-path tests need work. |
| Web | 70% | Pages exist broadly; accessibility/API typing/manual QA gaps remain. |
| Mobile | 58% | Customer app exists; release packaging still has template TODOs. |
| DevOps/docs | 72% | CI/deploy docs exist; pip-audit policy and migration protocol needed. |

Headline numbers:

- In-scope status counts: Done 24; Implemented weakly tested 11; Partial 13; Missing 3; Deferred/out of V1 5; WhatsApp-excluded items not counted.
- Backlog size: 28 items total; P0 = 5, P1 = 18, P2 = 5.
- P0/P1 effort: 66-104 ideal developer-days. All items: 85-133 ideal developer-days.
- Six-developer calendar estimate: 4-6 weeks for P0/P1; 6-8 weeks including P2 and integration hardening.

## Top 10 Risks

1. Parallel Alembic migrations create multiple heads without CI enforcement.
2. Critical endpoints are not uniformly idempotent.
3. Rate limits are uneven outside login/OTP/journey paths.
4. Retention/privacy lifecycle is effectively missing.
5. Observability is log-heavy but lacks clear queue/worker health.
6. Data classification is not a central enforceable catalogue.
7. Admin/institution endpoint coverage is broad but uneven.
8. Accessibility has no automated or formal manual gate.
9. Docs/code mismatch around `/schemas` and `platform.inbox` may confuse developers.
10. Shared files with the WhatsApp owner create merge-conflict risk.

## P0 List

B-001 Alembic/CI migration protocol; B-002 idempotency coverage; B-003 rate-limit coverage; B-004 retention/privacy lifecycle baseline; B-005 observability minimum.

## Critical Path

Wave 0: B-001 plus WhatsApp-owner shared-file plan. Wave 1: B-002/B-003/B-004 controls and core domain tests. Wave 2: observability/admin/web/mobile hardening. Wave 3: integration QA and docs.

## Open Questions

1. Should `/schemas` become a real top-level folder, or should docs be updated to say schemas are Pydantic-generated?
2. Is `EventDelivery` officially the consumer inbox, or do you want a separate `platform.inbox` table?
3. Should notification digests be implemented in V1, or explicitly deferred?
4. What is the minimum acceptable retention policy for V1-test versus production?
5. Is V1 English-only, or do you require a localisation foundation now?
6. What accessibility standard should gate V1: WCAG 2.1 AA checklist, automated axe smoke, or manual QA only?
7. Should `pip-audit` fail CI on high/critical vulnerabilities?
8. Who owns cross-workstream migration review: WS1 developer or a separate tech lead?
9. Which admin endpoints are release-critical enough to require full regression tests?
10. Are product extraction edge cases required before V1 demo, or can they be P1 after core controls?

## 7th Role Recommendation

Recommended: add a 7th role as integrator/tech lead/QA captain for 4-6 weeks. The role should own migration sequencing, CODEOWNERS enforcement, cross-workstream review, release checklist, and manual QA coordination. Without this role, WS1 will be overloaded and merge risk rises.
