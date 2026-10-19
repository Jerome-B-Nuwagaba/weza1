# WEZA Traceability And Status Matrix

Status legend: Done = implemented and covered by passing non-WhatsApp tests. Implemented, weakly tested = code exists but test coverage is indirect or missing. Partial = implemented with material requirement gaps. Missing = no clear implementation. Contradicted = code/docs disagree materially. Deferred = out of V1. WhatsApp-specific findings are excluded except shared-file coordination.

## Test Baseline And Scans

- VERIFIED: Backend tests passed on Windows with `.venv\Scripts\python -m pytest`: `68 passed, 3 xfailed in 88.93s`. The xfails are WhatsApp-specific and out of this backlog. Evidence: `services/core-api/tests/test_whatsapp_channel.py:269`, `services/core-api/tests/test_whatsapp_channel.py:280`, `services/core-api/tests/test_whatsapp_channel.py:306`.
- VERIFIED: CI runs core API lint/security/tests, Docker smoke test, web typecheck/build, Flutter analyze/test/build, and gitleaks. Evidence: `.github/workflows/ci.yml:13-42`, `.github/workflows/ci.yml:44-67`, `.github/workflows/ci.yml:69-84`, `.github/workflows/ci.yml:88-113`, `.github/workflows/ci.yml:115-124`.
- VERIFIED: TODO/FIXME scan found non-WhatsApp Android template TODOs only. Evidence: `apps/mobile/android/app/build.gradle.kts:18`, `apps/mobile/android/app/build.gradle.kts:34`.
- VERIFIED: pass-only scan found expected exception marker classes and duplicate-message ignore; no non-WhatsApp empty stubs. Evidence: `services/core-api/weza/domains/intelligence/ai.py:89-90`, `services/core-api/weza/domains/need/service.py:108-112`.
- VERIFIED: Only one Alembic revision exists. Evidence: `services/core-api/migrations/versions/0001_initial_schema.py`.
- VERIFIED: Docs mention versioned `/schemas`, but no top-level `schemas/` folder exists in `rg --files`; AI schemas live as Pydantic models. Evidence: `docs/blueprint/07-ai-and-agents.md:7`, `services/core-api/weza/domains/intelligence/ai.py:43-87`.
- VERIFIED: Docs mention `platform.inbox`; code uses `EventDelivery` as consumer inbox/dedupe rather than a separate table. Evidence: `docs/blueprint/08-runtime-events.md:48`, `services/core-api/weza/platform/models.py:34-48`.

## Matrix

| ID | Requirement summary | Status | Evidence | Gap description | Effort | Risk | Domain | Layer |
|---|---|---|---|---|---:|---|---|---|
| FR-001 | Start non-WhatsApp customer journey + attribution | Done | `api/v1/public.py:104-112`; `domains/need/service.py:36-61`; `tests/test_customer_journey.py:43-75` | WhatsApp excluded. | S | Low | need/commercial | API/domain |
| FR-002 | Extract and confirm intent | Done | `domains/need/journey.py:130-194`; `domains/intelligence/ai.py:212-248`; `tests/test_customer_journey.py:30-40` | None material. | S | Low | need/intelligence | domain |
| FR-003 | Dynamic questions | Done | `domains/customer/service.py:162-175`; `domains/need/journey.py:340-448`; `tests/test_customer_journey.py:111-118` | Admin UI for question-path editing is limited. | M | Medium | customer/admin | domain/web |
| FR-004 | OTP controls | Partial | `domains/identity/service.py:75-140`; `tests/test_customer_journey.py:122-137` | Real SMS delivery excluded; customer session/browser token UX is covered, but OTP delivery alternatives are not. | S | Low | identity | domain |
| FR-005 | Identity/profile/documents | Partial | `domains/customer/models.py:74-101`; `domains/customer/documents.py:30`; `api/v1/customer.py:216-239` | Document scan is BASIC adapter; production scanner is deferred, but document extraction/confirmation coverage is weak. | M | Medium | customer | domain/API |
| FR-006 | Readiness and Quality Score | Implemented, weakly tested | `domains/customer/service.py:178-198`; `domains/need/journey.py:473-486` | Unit tests do not directly assert factor weighting edge cases. | S | Medium | customer/need | domain |
| FR-007 | Match active product/appetite/capacity | Done | `domains/matching/engine.py:111-244`; `tests/test_customer_journey.py:43-75`; `tests/test_marketplace.py:84-112` | None material. | S | Low | matching | domain |
| FR-008 | Match score and reasons | Done | `domains/matching/engine.py:163-229`; `domains/matching/engine.py:540`; `tests/test_customer_journey.py:48-55` | None material. | S | Low | matching | domain |
| FR-009 | Options + preference ranking | Partial | `domains/need/journey.py:575-647`; `apps/web/components/chat/Conversation.tsx:384` | Preference UX exists, but ranking preferences lack dedicated tests and clear acceptance coverage. | M | Medium | matching/web | domain/web |
| FR-010 | Versioned consent | Done | `domains/consent/service.py:40-87`; `tests/test_security.py:57-80` | None material. | S | Low | consent | domain |
| FR-011 | Versioned opportunity snapshot | Done | `domains/opportunity/service.py:146-177`; `tests/test_customer_journey.py:64-68` | None material. | S | Low | opportunity | domain |
| FR-012 | Route only after consent/duplicate checks | Done | `domains/opportunity/service.py:109-196`; `tests/test_customer_journey.py:89-108`; `tests/test_security.py:41-80` | None material. | S | Low | opportunity/trust | domain |
| FR-013 | Institution registration/verification | Done | `api/v1/public.py:280-287`; `domains/institution/service.py:43-90`; `tests/test_institution.py:11-31` | None material. | S | Low | institution | API/domain |
| FR-014 | Tenant workspace + RBAC | Done | `domains/trust/policy.py:25-83`; `tests/test_security.py:33-100` | None material. | S | Low | trust/identity | domain/API |
| FR-015 | AI product extraction draft only | Implemented, weakly tested | `api/v1/institution.py:268`; `domains/product/service.py:1-2`; `domains/intelligence/ai.py:264-279` | Product extraction path lacks focused tests for malformed docs, provenance and draft-only enforcement. | M | Medium | product/intelligence | API/domain |
| FR-016 | Product lifecycle maker-checker | Done | `domains/product/service.py:51-135`; `tests/test_institution.py:41-50` | None material. | S | Low | product | domain |
| FR-017 | Appetite, mandates, capacity | Done | `domains/appetite/service.py:53-203`; `domains/matching/engine.py:53-95`; `tests/test_institution.py:53-76` | None material. | S | Low | appetite | domain |
| FR-018 | Simulation vs anonymised demand | Done | `domains/appetite/service.py:100-121`; `domains/matching/engine.py:445-520`; `tests/test_institution.py:59-63` | None material. | S | Low | appetite/matching | domain |
| FR-019 | Activation checklist | Done | `domains/institution/service.py:108-146`; `tests/test_institution.py:67-76` | None material. | S | Low | institution | domain |
| FR-020 | Role-personalised Command Centre | Done | `domains/intelligence/insights.py:38-122`; `tests/test_institution.py:87-92` | None material. | S | Low | intelligence | API/web |
| FR-021 | Intelligent feed | Implemented, weakly tested | `api/v1/institution.py:532-559`; `apps/web/app/institution/feed/page.tsx` | Feed endpoint/page exist, but ranking/explainability UI has indirect coverage only. | M | Medium | opportunity/web | API/web |
| FR-022 | Preview + interest | Implemented, weakly tested | `domains/opportunity/models.py:101-116`; `api/v1/institution.py:671-706`; `tests/test_security.py:83-91` | Allow-list is tested, but preview-interest workflow and feature-flag states are thinly tested. | M | Medium | opportunity | API/web |
| FR-023 | Assignment | Done | `domains/opportunity/service.py:264-336`; `tests/test_customer_journey.py:68-72` | None material. | S | Low | opportunity | domain |
| FR-024 | Service targets/escalation | Done | `domains/opportunity/service.py:545-573`; `domains/notification/service.py:194-207`; `tests/test_marketplace.py:168-182` | Channel escalation beyond in-app/email is excluded. | S | Medium | opportunity/notification | worker |
| FR-025 | Reported outcomes | Done | `domains/opportunity/service.py:395-419`; `tests/test_marketplace.py:41-64` | None material. | S | Low | opportunity | API/domain |
| FR-026 | No-lead/Radius | Implemented, weakly tested | `domains/matching/engine.py:493-520`; `api/v1/institution.py:743-758`; `apps/web/app/institution/radius/page.tsx` | Radius/no-lead acceptance coverage is narrow. | M | Medium | intelligence/matching | API/web |
| FR-027 | Waiting rooms | Partial | `domains/matching/engine.py:521-535`; `worker.py:52-68`; `tests/test_marketplace.py:117-146` | Institution mandate waiting is simplified; customer notifications overlap excluded channel work. | M | Medium | matching/notification | worker |
| FR-028 | Demand analytics | Implemented, weakly tested | `domains/intelligence/insights.py:136-199`; `api/v1/institution.py:749-758` | No dedicated tests for demand/product gap endpoints. | M | Medium | intelligence | API/web |
| FR-029 | Conversational institutional AI | Done/partial | `domains/intelligence/assistant.py:36-255`; `tests/test_institution.py:95-102` | Deterministic/tool path tested; AI provider response path not tested beyond fallback assumptions. | M | Medium | intelligence | domain |
| FR-030 | Role-aware notifications/digests | Partial | `domains/notification/service.py:73-207`; `api/v1/institution.py:911-939` | In-app/email and escalation exist; digests are not evident; channel adapters excluded. | M | Medium | notification | domain/worker |
| FR-031 | Outcome mismatch insights | Done | `domains/intelligence/insights.py:201-261`; `tests/test_institution.py:105-111` | None material. | S | Low | intelligence | worker |
| FR-032 | Rescue with renewed consent | Done | `domains/need/journey.py:756-771`; `tests/test_marketplace.py:149-165` | None material. | S | Low | opportunity/matching | graph |
| FR-033 | Freshness/stale | Done | `domains/opportunity/service.py:590`; `tests/test_marketplace.py:168-182` | None material. | S | Low | opportunity | worker |
| FR-034 | Duplicate/suspicious detection | Partial | `domains/opportunity/service.py:141-196`; `domains/integrity/service.py:80`; `api/v1/admin.py:280-296` | Integrity detection exists, but abnormal velocity/device/referral patterns are under-specified and weakly tested. | M | High | integrity | domain/admin |
| FR-035 | Attribution + billing | Done | `domains/commercial/service.py:34-80`; `tests/test_customer_journey.py:70-75`; `tests/test_marketplace.py:67-81` | None material. | S | Low | commercial | domain |
| FR-036 | Billing disputes | Done | `domains/commercial/service.py:106-117`; `api/v1/admin.py:324-356`; `tests/test_marketplace.py:69-81` | None material. | S | Low | commercial | API/domain |
| FR-037 | Network Control Centre | Implemented, weakly tested | `api/v1/admin.py:59-84`; `apps/web/app/admin/page.tsx` | Admin overview exists; little endpoint-by-endpoint test coverage. | M | Medium | admin | API/web |
| FR-038 | Audit trail | Done | `domains/trust/models.py:15-30`; `tests/test_security.py:130-140` | None material. | S | Low | trust | DB/domain |
| FR-039 | Zero integration/funds boundary | Done | `tests/test_security.py:142-152`; `docs/source/WEZA_Technical_Specification_Document_v1.0.docx §83-84` | Test allows outbound AI/channel HTTP only. | S | Low | architecture | test |
| FR-040 | Suspension/network controls | Done/partial | `api/v1/admin.py:135-170`; `api/v1/admin.py:629-653`; `tests/test_marketplace.py:101-112` | Channel disable overlaps WhatsApp owner; product/appetite/pause tested. | S | Medium | admin/platform | API |
| NFR-001 | Security/RBAC/privacy | Done/partial | `tests/test_security.py:33-152`; `domains/trust/policy.py:108-141` | Good backend coverage; frontend access-control assumptions need QA. | M | High | trust/web | cross |
| NFR-002 | Data classification | Partial | `domains/customer/models.py:87`; `domains/trust/policy.py:89-97`; `platform/logging.py:11-30` | Field classification is not universal or centrally enforced. | L | High | trust/platform | cross |
| NFR-003 | Decision ledger | Implemented, weakly tested | `domains/trust/service.py:31-38`; `domains/matching/engine.py:325`; `domains/opportunity/service.py:185` | No comprehensive reconstruction test. | M | Medium | trust | domain/test |
| NFR-004 | Outbox/retry/dead-letter | Done/partial | `platform/events.py:57-129`; `worker.py:120-130`; `api/v1/admin.py:545-559` | Separate `platform.inbox` doc mismatch; EventDelivery substitutes but docs need correction or code alignment. | M | Medium | platform | worker |
| NFR-005 | Idempotency | Partial | `platform/controls.py:43-59`; `domains/opportunity/models.py:21`; `tests/test_customer_journey.py:89-108` | Header idempotency not applied uniformly to critical outcome/report endpoints. | M | High | platform/API | API |
| NFR-006 | Rate limiting | Partial | `platform/controls.py:18-35`; `api/v1/public.py:282`; `domains/identity/service.py:79-81` | Coverage focuses login/OTP; upload/simulation/AI broad limits need audit. | M | High | platform | API |
| NFR-007 | Observability | Partial | `main.py:51-69`; `platform/logging.py:33-57`; `domains/misc_models.py:119-149` | No metrics endpoint/queue-depth health; logs exist. | L | Medium | platform | ops |
| NFR-008 | Retention/privacy lifecycle | Missing | TSD §70; `domains/customer.models.py`, `domains/identity.models.py` | No retention engine found. | L | High | platform/trust | worker |
| NFR-009 | Country/localisation | Partial | `domains/admin_config.py`; `domains/intelligence/parsing.py:210-240` | Uganda-heavy parsing/config; no localisation catalogue. | L | Medium | admin/platform | domain/web |
| NFR-010 | Accessibility | Missing/weak | BRD §38; web pages under `apps/web/app` | No automated a11y tests or explicit checklist. | M | Medium | web | QA |
| NFR-011 | AI degradation | Done | `domains/intelligence/ai.py:140-199`; `tests/test_customer_journey.py:171-178` | None material. | S | Low | intelligence | domain |
| NFR-012 | CI/CD | Done/partial | `.github/workflows/ci.yml:13-124`; `render.yaml:1-52`; `apps/web/vercel.json:1-6` | `pip-audit` is allowed to fail; no Alembic multi-head check. | M | Medium | DevOps | CI |
| NFR-013 | Non-goals | Done | `tests/test_security.py:142-152`; `domains/opportunity/service.py:397` | None material. | S | Low | architecture | test |

## Endpoint And Surface Coverage Findings

- VERIFIED: API endpoint surface is broad: auth, customer, public, institution and admin routers expose all major V1 areas. Evidence: `main.py:73`, route scan of `services/core-api/weza/api/v1`.
- VERIFIED: Backend tests are organised by customer journey, institution, marketplace, graph runtime, security, and WhatsApp channel; no dedicated non-WhatsApp tests exist for many individual admin/institution endpoints. Evidence: `services/core-api/tests/test_customer_journey.py`, `services/core-api/tests/test_institution.py`, `services/core-api/tests/test_marketplace.py`, `services/core-api/tests/test_security.py`.
- VERIFIED: Web pages exist for most blueprint screens, including customer status/profile/documents, institution feed/products/appetite/routing/notifications/billing/intelligence, and admin graph/audit/config/deliveries. Evidence: `apps/web/app/**` file list in repo.
- VERIFIED: Flutter client covers start/resume journey, profile, needs, notifications, withdrawal, and shared API error handling. Evidence: `apps/mobile/lib/api.dart:71-101`.

## Coordination Files

These files are shared with WhatsApp/messaging work. Non-WhatsApp workstreams must coordinate before touching them: `services/core-api/weza/api/v1/public.py`, `services/core-api/weza/domains/need/service.py`, `services/core-api/weza/domains/notification/service.py`, `services/core-api/weza/config.py`, `services/core-api/.env.example`, `apps/web/app/page.tsx`, `apps/web/components/chat/Conversation.tsx`, `apps/web/lib/api.ts`.
