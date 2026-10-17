# Workstream 4: Institution, Intelligence, Commercial And Admin API

## Goal

Fill weak test and workflow coverage for institution supply, product extraction, previews, intelligence, admin controls and reporting.

## Why It Matters

Institutions are the paying side of the marketplace. Their workflows must be credible, explainable and tenant-safe before V1 rollout.

## Repo Orientation

- Institution API: `weza/api/v1/institution.py`.
- Admin API: `weza/api/v1/admin.py`.
- Product/appetite services: `weza/domains/product`, `weza/domains/appetite`.
- Intelligence: `weza/domains/intelligence`.
- Commercial: `weza/domains/commercial`.
- Integrity: `weza/domains/integrity`.
- Institution tests: `test_institution.py`, marketplace tests: `test_marketplace.py`.
- Web institution pages: `apps/web/app/institution`.
- Web admin pages: `apps/web/app/admin`.
- Coordinate migrations with WS1.
- Do not edit WhatsApp files.

## Backlog Order

1. B-010: Product extraction robustness.
2. B-012: Preview/interest workflow tests.
3. B-014: Demand intelligence/product gap tests.
4. B-011: Opportunity feed ranking/explanations tests.
5. B-021: Admin endpoint coverage sweep.
6. B-024: AI provider-path tests with fake provider.

## Owns / Avoids

Owns institution/admin APIs and supply/intelligence/commercial domains. Avoid platform controls without WS2 and migrations without WS1.

## Verification

Run full backend suite. Manually sign in as institution roles, create/approve product and appetite, run sandbox/radius/ask/admin graph flows.

## Definition Of Done

Each endpoint touched has role/tenant tests, intelligence stays non-identifying, and AI never writes consequential state autonomously.

## First-Day Checklist

Read `api/v1/institution.py`, `api/v1/admin.py`, `test_institution.py`; start B-010.
