# 11 — Requirements Traceability Matrix

Primary key is the FSD FR register (C4). The BRD column shows the equivalent BRD FR / business rule. "Tests" refers to the acceptance-test IDs in [12-backlog-and-qa.md](12-backlog-and-qa.md) §2. Status is updated during implementation (P = planned, B = built, V = verified by test). The live matrix is maintained at `docs/traceability.csv`.

| FSD FR | Requirement | BRD | TSD | Module(s) | Screens | Graph | Tests | Phase |
|---|---|---|---|---|---|---|---|---|
| FR-001 | Start journey WhatsApp/web + attribution | FR-001 | §5–6, §73 | need, commercial.attribution, channels | C-01, C-02, C-03 | G1 | AT-01, AT-02 | 1 |
| FR-002 | Extract & confirm intent | FR-002 | §9–10 | intelligence.ai, need | C-02 | G1 | AT-03, AT-04 | 1 |
| FR-003 | Dynamic questioning | FR-005 | §14 | customer, admin.question_path | C-02 | G1 | AT-05 | 1 |
| FR-004 | Phone OTP w/ controls | FR-003 | §13, §63 | identity | C-04 | G1 | AT-06…AT-09 | 1 |
| FR-005 | Identity/profile/documents | FR-004 | §11–12, §42 | identity.vault, customer | C-05, C-06 | G1, doc | AT-10, AT-11 | 1 |
| FR-006 | Readiness + Quality Score explainable | FR-007 | §19 | customer.readiness | C-07, I-07 | G1 | AT-12 | 3 |
| FR-007 | Match vs products/appetite/capacity | FR-007 | §17–24 | matching | C-07 | G4 | AT-13, AT-14 | 3 |
| FR-008 | Institution-specific score + reasons | FR-008 | §20–21 | matching | C-07, C-08, I-07 | G4 | AT-15 | 3 |
| FR-009 | Options + preference ranking | FR-009, FR-010 | §19 | matching | C-07, C-13 | G1 | AT-16 | 3 |
| FR-010 | Institution-specific versioned consent | FR-006 | §27 | consent | C-09 | G1 | AT-17, AT-18 | 3 |
| FR-011 | Versioned Qualified Opportunity snapshot | FR-011 | §30 | opportunity | C-10, I-07 | G3 | AT-19 | 4 |
| FR-012 | Route only after consent + duplicate checks | BR-001 | §29–32 | opportunity, trust, integrity | — | G3 | AT-20, AT-21, AT-SEC-03 | 4 |
| FR-013 | Institution registration + verification | FR-012 | — | institution, admin | I-01, A-02 | G2 | AT-22 | 2 |
| FR-014 | Tenant-isolated workspace + RBAC | FR-013 | §47–48 | identity, trust | I-21 | G2 | AT-SEC-01, AT-SEC-02 | 0/2 |
| FR-015 | AI product extraction + human approval | §11 | §9, §42 | intelligence, product | I-11 | product_extraction | AT-23 | 2 |
| FR-016 | Product Studio + lifecycle | FR-014 | §16 | product | I-10 | G2 | AT-24 | 2 |
| FR-017 | Appetite Studio, mandates, capacity | FR-015 | §17, §24 | appetite | I-12 | G2, G6 | AT-25, AT-26 | 2 |
| FR-018 | Simulate vs anonymised demand | FR-016 | §37, §39 | matching.simulator | I-13 | G2 | AT-27 | 2 |
| FR-019 | Activation checklist + go-live | FR-019 | — | institution | I-03 | G2 | AT-28 | 2 |
| FR-020 | Role-personalised Command Centre | FR-024 | — | intelligence.briefing | I-04 | — | AT-29 | 5 |
| FR-021 | Intelligent feed + explainable ranking | FR-020 | — | opportunity | I-06 | — | AT-30 | 4 |
| FR-022 | Anonymised preview + interest | — | §25–26 | opportunity.preview | I-08 | — | AT-31 | 8 |
| FR-023 | Auto/manual assignment + unassigned | FR-022 | §33 | opportunity | I-06, I-09 | G3 | AT-32 | 4 |
| FR-024 | Service targets + escalation | FR-017 | §33, §62 | opportunity, notification | I-05 | G3, L6 | AT-33 | 5 |
| FR-025 | Lightweight reported outcomes | FR-023, BR-005 | — | opportunity | I-07, C-11 | G3 | AT-34 | 5 |
| FR-026 | No-lead, near-match, Radius | FR-025, BR-010 | §40 | intelligence | I-15, I-04 | — | AT-35 | 7 |
| FR-027 | Customer + institution Waiting Rooms | — | §23 | matching | C-12 | G5, G4 | AT-36 | 7 |
| FR-028 | Demand analytics w/o bank DB | FR-026 | §38–39 | intelligence | I-16, I-17 | L2 | AT-37 | 7 |
| FR-029 | Conversational querying under RBAC | FR-027 | §35–36 | intelligence.assistant | I-19 | — | AT-38, AT-SEC-04 | 8 |
| FR-030 | Role-aware notifications + digests | FR-018, FR-028 | §34 | notification | I-23 | L5 | AT-39 | 5 |
| FR-031 | Appetite/outcome mismatch insights | §27, BR-004 | — | intelligence | I-18 | L1, G6 | AT-40 | 7 |
| FR-032 | Rescue with renewed consent | FR-030, BR-006 | — | opportunity, matching | C-11 | G7 | AT-41 | 7 |
| FR-033 | Freshness / stale / expired | FR-031 | §62 | opportunity | I-06, C-11 | L6 | AT-42 | 5 |
| FR-034 | Duplicate / suspicious detection | FR-031 | §41 | integrity | A-07 | L4 | AT-43 | 4 |
| FR-035 | Attribution + billing events | BR-009 | §43–45 | commercial | I-24, A-09 | L3 | AT-44, AT-45 | 6 |
| FR-036 | Billing disputes | — | §46 | commercial | I-24, A-08 | dispute | AT-46 | 6 |
| FR-037 | Network Control Centre | FR-032 | — | admin | A-01, A-03 | — | AT-47 | 5 |
| FR-038 | Audit trail | FR-029 | §52–53 | trust.audit | A-11, I-25 | all | AT-48 | 0 |
| FR-039 | Zero-integration + funds boundary | §3.2, BR-003, BR-007 | §83–84 | (architecture) | C-09 copy | — | AT-49 | all |
| FR-040 | Suspension + network health controls | FR-032 | §75 | admin | A-13 | G4 | AT-50 | 5 |

### Business rules
| BR | Enforcement | Test |
|---|---|---|
| BR-001 no identifiable data before consent | Disclosure Gateway + saga precondition | AT-SEC-03 |
| BR-002 match ≠ approval probability | copy component + lint test on UI strings | AT-15 |
| BR-003 KYC/credit stays with institution | no approval capability exists; copy | AT-49 |
| BR-004 no auto change of product/appetite | AI has no write tools; insight → draft only | AT-40 |
| BR-005 outcomes labelled reported | `ReportedBadge` component, API field `reported_by` | AT-34 |
| BR-006 no reuse across institutions w/o consent | consent per institution; gateway checks institution_id | AT-41 |
| BR-007 phone ≠ disbursement destination | not stored as payout field; copy | AT-49 |
| BR-008 paid ≠ suitability | sponsored slot separate (disabled) | AT-16 |
| BR-009 billable only if definition met | contract evaluator | AT-44 |
| BR-010 no-lead shows intelligence | empty-state component | AT-35 |

### Key TSD sections
| TSD | Implementation |
|---|---|
| §31 server-enforced transitions | `transition()` tables · AT-GR-02 |
| §52 decision ledger | `trust.decision` on readiness, match, clearing, routing, PDP · AT-51 |
| §55–57 outbox, at-least-once, DLQ | platform.outbox/inbox/dead_letter · AT-GR-05 |
| §59 error contract | exception handlers · AT-API-01 |
| §60 idempotency | middleware + unique keys · AT-GR-06 |
| §66 log redaction | redaction filter · AT-SEC-06 |
| §71 country config | admin.country_config · AT-52 |
| §74 sandbox | synthetic partition · AT-53 |
| §76 AI degradation | AI modes · AT-54 |
