# Workstream 1: Platform, CI, Ops And Migrations

## Goal

Make the shared engineering rails reliable: migrations, CI checks, outbox/doc alignment and production observability.

## Why It Matters

Six developers will add code in parallel. Without a migration protocol and shared CI checks, WEZA can look green locally while accumulating multiple Alembic heads or unobservable worker failures.

## Repo Orientation

- API lives in `services/core-api`; run tests from there with `.venv\Scripts\python -m pytest`.
- Local API command from README: `python scripts/dev_api.py` after installing requirements.
- Web app lives in `apps/web`; run `npm install` then `npm run dev`.
- Mobile app lives in `apps/mobile`; CI runs Flutter analyze/test/build.
- CI is `.github/workflows/ci.yml`.
- Migrations live in `services/core-api/migrations/versions`.
- Outbox/worker code is `weza/platform/events.py` and `weza/worker.py`.
- Deployment config is `render.yaml` and `apps/web/vercel.json`.
- Do not edit WhatsApp channel code.
- Coordinate any migration touching shared models with the relevant workstream.

## Backlog Order

1. B-001: Alembic single-head CI and migration protocol.
2. B-005: Observability minimum for DB/outbox/worker health.
3. B-022: Align outbox/inbox docs and code.
4. B-027: Replace permissive `pip-audit || true` with allow-list policy.

## Owns / Avoids

Owns `.github/workflows`, migrations, Alembic config, deployment docs. Avoid domain service rewrites and `domains/notification/service.py` unless reviewed by the WhatsApp owner.

## Verification

Run `alembic heads` and prove CI fails on multiple heads. Run `.venv\Scripts\python -m pytest`. Smoke `/healthz` and admin delivery/queue views.

## Definition Of Done

Single migration head enforced, CI policy documented, health/queue visibility implemented, and no WhatsApp files touched without review.

## First-Day Checklist

Read `ci.yml`, `migrations/env.py`, `platform/events.py`, `worker.py`, `render.yaml`; then open B-001 as the first small PR.
