# Workstream 2: Security, Privacy And Controls

## Goal

Close release-blocking control gaps around idempotency, rate limiting, retention and field classification.

## Why It Matters

WEZA handles consented financial demand and identity-adjacent data. The backend has strong foundations, but production readiness needs consistent controls across all critical endpoints, not just the happy path.

## Repo Orientation

- Tests: `cd services/core-api && .venv\Scripts\python -m pytest`.
- Security tests are in `services/core-api/tests/test_security.py`.
- Trust policy/audit: `weza/domains/trust`.
- Rate limits/idempotency: `weza/platform/controls.py`.
- Identity vault/OTP: `weza/domains/identity`.
- Customer facts/docs: `weza/domains/customer`.
- Standard errors: `weza/platform/errors.py`.
- Do not edit `api/v1/public.py` without WhatsApp-owner coordination.
- Coordinate migrations through WS1.
- Web and mobile use `/api/v1` and expect the standard error contract.

## Backlog Order

1. B-003: Rate-limit coverage for upload, simulation and AI endpoints.
2. B-002: Idempotency for critical non-channel endpoints.
3. B-018: Central data classification map.
4. B-004: Retention/privacy lifecycle baseline.

## Owns / Avoids

Owns `domains/trust`, `platform/controls.py`, security tests and retention policy. Avoid broad router reshapes; prefer small dependency/helper additions.

## Verification

Run targeted security tests plus full backend suite. Manually replay critical POSTs with the same idempotency key and verify no duplicate outcomes/billing/activity.

## Definition Of Done

Every new control has a test, error responses use the standard contract, retention excludes immutable audit/commercial records, and sensitive fields are classified.

## First-Day Checklist

Map critical POST endpoints, mark which are idempotent/rate-limited today, then start B-003.
