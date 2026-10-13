# WEZA Requirements Inventory

Scope note: WhatsApp and real SMS delivery work is excluded. Requirements that mention WhatsApp are retained only when the non-WhatsApp portion is in V1. Evidence labels use VERIFIED for read files/tests and INFERRED only where the code/doc boundary is ambiguous.

## Source Baseline

- VERIFIED: Repository/product scope is documented as core API, web, mobile, blueprint and source docs. Evidence: `README.md:12-18`.
- VERIFIED: Approved V1 traceability has 40 FSD functional requirements plus ten BR guardrails. Evidence: `docs/blueprint/11-traceability.md:5-60`.
- VERIFIED: Backend baseline on this machine: `68 passed, 3 xfailed in 88.93s`; the 3 xfails are WhatsApp-specific tests and excluded from this backlog. Evidence: test run on 2026-10-13; `services/core-api/tests/test_whatsapp_channel.py:269`, `services/core-api/tests/test_whatsapp_channel.py:280`, `services/core-api/tests/test_whatsapp_channel.py:306`.

## Functional Requirements

| ID | Source | Requirement | V1/Later | WhatsApp-excluded |
|---|---|---|---|---|
| FR-001 | FSD §51; blueprint traceability | Start customer journey through approved non-WhatsApp channels with acquisition attribution. | V1 | Partial exclusion: WhatsApp channel only |
| FR-002 | FSD §51; `docs/blueprint/11-traceability.md:8` | Extract and confirm financial intent before consequential use. | V1 | No |
| FR-003 | FSD §51; `docs/blueprint/11-traceability.md:9` | Ask dynamic profile questions from configurable paths. | V1 | No |
| FR-004 | FSD §51; `docs/blueprint/11-traceability.md:10` | Phone OTP with expiry, attempt/resend controls and lockout. | V1 | Real SMS excluded |
| FR-005 | FSD §51; `docs/blueprint/11-traceability.md:11` | Identity/profile/documents with provenance and scan pipeline. | V1 | No |
| FR-006 | FSD §51; `docs/blueprint/11-traceability.md:12` | Readiness and WEZA Quality Score must be explainable and not a credit score. | V1 | No |
| FR-007 | FSD §51; `docs/blueprint/11-traceability.md:13` | Match need against active products, appetite and capacity. | V1 | No |
| FR-008 | FSD §51; `docs/blueprint/11-traceability.md:14` | Store institution-specific match score and reasons. | V1 | No |
| FR-009 | FSD §51; `docs/blueprint/11-traceability.md:15` | Present ranked options and customer preference ranking. | V1 | No |
| FR-010 | FSD §51; `docs/blueprint/11-traceability.md:16` | Institution-specific versioned consent before routing. | V1 | No |
| FR-011 | FSD §51; `docs/blueprint/11-traceability.md:17` | Create versioned Qualified Opportunity snapshots. | V1 | No |
| FR-012 | FSD §51; `docs/blueprint/11-traceability.md:18` | Route only after consent, duplicate/integrity checks and saga safeguards. | V1 | No |
| FR-013 | FSD §51; `docs/blueprint/11-traceability.md:19` | Institution registration and WEZA verification. | V1 | No |
| FR-014 | FSD §51; `docs/blueprint/11-traceability.md:20` | Tenant-isolated institution workspace and RBAC. | V1 | No |
| FR-015 | FSD §51; `docs/blueprint/11-traceability.md:21` | AI product extraction creates draft configuration only, with human approval. | V1 | No |
| FR-016 | FSD §51; `docs/blueprint/11-traceability.md:22` | Product Studio lifecycle with maker-checker. | V1 | No |
| FR-017 | FSD §51; `docs/blueprint/11-traceability.md:23` | Appetite Studio, mandate criteria and capacity states. | V1 | No |
| FR-018 | FSD §51; `docs/blueprint/11-traceability.md:24` | Simulate appetite against anonymised demand. | V1 | No |
| FR-019 | FSD §51; `docs/blueprint/11-traceability.md:25` | Activation checklist gates institution go-live. | V1 | No |
| FR-020 | FSD §51; `docs/blueprint/11-traceability.md:26` | Role-personalised Command Centre. | V1 | No |
| FR-021 | FSD §51; `docs/blueprint/11-traceability.md:27` | Intelligent opportunity feed and explainable ranking. | V1 | No |
| FR-022 | FSD §51; `docs/blueprint/11-traceability.md:28` | Anonymised opportunity preview and institution interest. | V1 simplified/flagged | No |
| FR-023 | FSD §51; `docs/blueprint/11-traceability.md:29` | Auto/manual assignment and unassigned handling. | V1 | No |
| FR-024 | FSD §51; `docs/blueprint/11-traceability.md:30` | Service targets and escalation. | V1 | No |
| FR-025 | FSD §51; `docs/blueprint/11-traceability.md:31` | Lightweight institution-reported outcomes. | V1 | No |
| FR-026 | FSD §51; `docs/blueprint/11-traceability.md:32` | No-lead intelligence, near-match analysis and Opportunity Radius. | V1 simplified | No |
| FR-027 | FSD §51; `docs/blueprint/11-traceability.md:33` | Customer and institution waiting rooms. | V1 simplified | Customer notification channel excluded where WhatsApp/SMS |
| FR-028 | FSD §51; `docs/blueprint/11-traceability.md:34` | Demand analytics without bank database access. | V1 simplified | No |
| FR-029 | FSD §51; `docs/blueprint/11-traceability.md:35` | Conversational institutional querying under RBAC. | V1 simplified | No |
| FR-030 | FSD §51; `docs/blueprint/11-traceability.md:36` | Role-aware notifications and digests. | V1 | Channel adapters excluded |
| FR-031 | FSD §51; `docs/blueprint/11-traceability.md:37` | Appetite/outcome mismatch insights; no autonomous appetite changes. | V1 simplified | No |
| FR-032 | FSD §51; `docs/blueprint/11-traceability.md:38` | Decline rescue with renewed consent. | V1 simplified | No |
| FR-033 | FSD §51; `docs/blueprint/11-traceability.md:39` | Opportunity freshness, stale and expiry handling. | V1 | No |
| FR-034 | FSD §51; `docs/blueprint/11-traceability.md:40` | Duplicate and suspicious-pattern detection. | V1 | No |
| FR-035 | FSD §51; `docs/blueprint/11-traceability.md:41` | Attribution and billing events. | V1 | No |
| FR-036 | FSD §51; `docs/blueprint/11-traceability.md:42` | Billing disputes and reversal events. | V1 | No |
| FR-037 | FSD §51; `docs/blueprint/11-traceability.md:43` | Network Control Centre. | V1 | No |
| FR-038 | FSD §51; `docs/blueprint/11-traceability.md:44` | Append-oriented audit trail. | V1 | No |
| FR-039 | FSD §51; `docs/blueprint/11-traceability.md:45` | Zero-core-integration and funds boundary. | V1 | No |
| FR-040 | FSD §51; `docs/blueprint/11-traceability.md:46` | Suspension and network health controls. | V1 | Channel disable overlaps WhatsApp owner |

## Business Guardrails

| ID | Source | Requirement | V1/Later | WhatsApp-excluded |
|---|---|---|---|---|
| BR-001 | BRD §40; `docs/blueprint/11-traceability.md:51` | No identifiable institution disclosure before valid consent. | V1 | No |
| BR-002 | BRD §40; `docs/blueprint/11-traceability.md:52` | Match is not approval probability. | V1 | No |
| BR-003 | BRD §39; `docs/blueprint/11-traceability.md:53` | Formal KYC/credit decision stays with institution. | V1 | No |
| BR-004 | BRD §40; `docs/blueprint/11-traceability.md:54` | No autonomous product/appetite changes. | V1 | No |
| BR-005 | BRD §40; `docs/blueprint/11-traceability.md:55` | Outcomes are labelled as institution-reported. | V1 | No |
| BR-006 | BRD §40; `docs/blueprint/11-traceability.md:56` | No cross-institution reuse without new consent. | V1 | No |
| BR-007 | BRD §40; `docs/blueprint/11-traceability.md:57` | Phone number must not be inferred as disbursement destination. | V1 | No |
| BR-008 | BRD §40; `docs/blueprint/11-traceability.md:58` | Paid placement must not masquerade as suitability. | V1 | No |
| BR-009 | BRD §40; `docs/blueprint/11-traceability.md:59` | Billable opportunities must satisfy contract definition. | V1 | No |
| BR-010 | BRD §40; `docs/blueprint/11-traceability.md:60` | No-lead states should surface near-match intelligence. | V1 | No |

## Non-Functional Requirements

| ID | Source | Requirement | V1/Later | WhatsApp-excluded |
|---|---|---|---|---|
| NFR-001 | BRD §38; FSD §52 | Security: authentication, authorisation, tenant isolation, consent, audit, data protection. | V1 | No |
| NFR-002 | TSD §47-49 | Data classification must drive logging, retention and disclosure controls. | V1 | No |
| NFR-003 | TSD §52-53 | Decision ledger and audit must reconstruct material determinations. | V1 | No |
| NFR-004 | TSD §55-57 | Transactional outbox, at-least-once delivery, retry/dead-letter/replay. | V1 | No |
| NFR-005 | TSD §60 | Idempotency for opportunity, billing, critical notifications and outcomes. | V1 | Notification channel excluded |
| NFR-006 | TSD §63 | Rate limiting and anti-automation for OTP, login, public messaging, uploads, AI, simulation, APIs. | V1 | Public messaging WhatsApp excluded |
| NFR-007 | TSD §64-67 | Observability: health, metrics, correlation IDs, redacted logs, AI logs. | V1 | No |
| NFR-008 | TSD §70 | Retention/privacy lifecycle. | V1 baseline | No |
| NFR-009 | TSD §71-72 | Country configuration and localisation. | V1 baseline | No |
| NFR-010 | BRD §38; FSD §52 | Accessibility and mobile-first web UX. | V1 | No |
| NFR-011 | TSD §76-77 | AI degradation and portability. | V1 | No |
| NFR-012 | TSD §80-81 | CI/CD, environments, IaC/feature flags. | V1 | No |
| NFR-013 | TSD §83-84 | Non-goals: no core banking, LOS, funds, autonomous underwriting. | V1 | No |

## Deferred Or Out Of V1

| ID | Source | Requirement | V1/Later | WhatsApp-excluded |
|---|---|---|---|---|
| DEF-001 | `docs/blueprint/13-deployment.md:26-30` | Azure target, production malware scanner, penetration test and DR test are production blockers, not V1-test implementation. | Later/production | No |
| DEF-002 | `docs/blueprint/README.md:103` | Institutional mobile app is not V1; Flutter is customer app only. | Later | No |
| DEF-003 | TSD §38 | Separate analytical lakehouse/Fabric layer may be introduced as scale requires. | Later | No |
| DEF-004 | Skill §57-58 | Marketplace digital twin and root-cause/causal analysis are longer-term. | Later | No |
| DEF-005 | `docs/blueprint/README.md:89` | Entra ID OIDC is planned behind an interface, not V1-test. | Later | No |
