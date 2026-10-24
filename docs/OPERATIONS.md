# WEZA operations: environments, backups and recovery

Written for TSD §79–81. It describes what to do and what to check; it does not provision anything. Provisioning (Render,
Neon or equivalent) needs your accounts.

## Environments

| Environment | Purpose | Data | Notes |
|---|---|---|---|
| local | Development | Seeded demo data | `ENV=local`, SQLite-free: uses PostgreSQL |
| CI | Every push | Throwaway database per run | `LOGIN_IP_LIMIT` raised for the browser tests only |
| uat | Acceptance and pilot rehearsal | Demo or synthetic data only, never real customers | `ENV=uat` |
| production | Real customers | Real data | `ENV=production`; see [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) |

Every environment is built from the same container image (`services/core-api/Dockerfile`) and differs only in settings
and secrets. No secret is stored in the repository; `services/core-api/.env` is local only.

## What runs

- **API**: one container, `uvicorn`
- **Worker**: runs inside the API process on Render (`RUN_WORKER_INPROCESS` in `render.yaml`): outbox, notifications, briefs, retention, expiry sweeps. It can also run alone with `python -m weza.worker`
- **Database**: PostgreSQL, one primary
- **Web**: the Next.js app (`apps/web`)
- **ClamAV**: sidecar the API calls for document scanning

Run exactly one API instance while the worker is in-process. Jobs are idempotent, but if you scale out, move the worker to its own single instance first.

## Backups

- Take automatic daily backups plus point-in-time recovery on the database provider; keep at least 14 days.
- Documents are stored encrypted; back up the document store with the same schedule.
- Back up the three keys (`SECRET_KEY`, `VAULT_MASTER_KEY`, `BLIND_INDEX_KEY`) in a separate secret store. A database
  backup is unreadable without `VAULT_MASTER_KEY` and `BLIND_INDEX_KEY`.
- The audit and decision ledgers are append-only in the database (migration 0017); a restore must not be used to edit them.

## Restore rehearsal (do once before launch, then every quarter)

1. Restore the latest backup into a new, empty database.
2. Start the API against it with production-like settings but `ENV=uat`.
3. Run `alembic current` and `alembic heads`: they must match.
4. Sign in as an administrator and open Admin, Customers and an opportunity; confirm documents open.
5. Record how long it took and what was missing. Target: recovery within 4 hours, no more than 15 minutes of data lost.

## Incident basics

- First action is containment: use the Admin kill switches (pause all routing, pause billing events, disable a channel, set AI mode) or pause the affected institution.
- Check `/healthz`, `/metrics` and the structured logs by `correlation_id`; logs redact personal data by classification.
- A suspected data exposure is escalated to the data protection lead the same day (BRD §19).
- After resolution, write down cause, timeline and the one change that prevents a repeat.

## Infrastructure as code

The repository holds `render.yaml` for the hosted web service. Keep any further infrastructure (database, storage, DNS) in
version control the same way once hosting is chosen; review it like application code.
