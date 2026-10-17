# Workstream 3: Customer, Matching And Opportunity

## Goal

Strengthen the customer-to-opportunity core: readiness, documents, preference ranking, waiting room, integrity and graph/decision traceability.

## Why It Matters

This is the marketplace engine. The main journey passes today, but V1 needs confidence in edge cases and support/admin explainability.

## Repo Orientation

- Customer graph: `weza/domains/need/journey.py`.
- Journey service/canonical messages: `weza/domains/need/service.py` (COORDINATE WITH WHATSAPP OWNER).
- Customer facts/docs: `weza/domains/customer`.
- Matching: `weza/domains/matching`.
- Opportunity saga/disclosure: `weza/domains/opportunity`.
- Worker sweeps: `weza/worker.py`.
- Tests: `test_customer_journey.py`, `test_marketplace.py`, `test_graph_runtime.py`.
- Run backend tests from `services/core-api`.
- Web customer pages are under `apps/web/app/c`.
- Avoid notification channel changes unless coordinated.

## Backlog Order

1. B-006: Quality score/readiness factor tests.
2. B-007: Document pipeline hardening tests.
3. B-009: Preference ranking acceptance coverage.
4. B-013: Waiting room lifecycle coverage.
5. B-016: Integrity pattern coverage.
6. B-017: Decision-ledger reconstruction test.

## Owns / Avoids

Owns customer/need/matching/opportunity domain files. Do not edit `domains/need/service.py` or `domains/notification/service.py` without WhatsApp-owner coordination.

## Verification

Run targeted tests and full backend suite. Manually complete web `/start` journey through options/consent/status; verify no identity appears before consent and Graph Inspector reconstructs the opportunity.

## Definition Of Done

New edge cases are tested, no duplicate opportunity/billing regressions, and decision/audit evidence remains visible.

## First-Day Checklist

Run the full tests, read the customer journey graph nodes, then start with B-006 and B-007.
