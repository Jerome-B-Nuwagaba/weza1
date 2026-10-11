# WEZA — Intelligent Financial Marketplace & Opportunity Network

> **Customer:** Tell WEZA what financing you need. · **Institution:** Tell WEZA what customers you want.
> **WEZA:** Understand. Qualify. Match. Route. Track. Learn.

WEZA connects customer financial demand with the products, eligibility, appetite and capacity of participating financial institutions. It needs **no integration with institutional core systems**. WEZA creates access; financial institutions make the credit decision.

**→ To test it, start with [docs/TESTING.md](docs/TESTING.md)** (live-link setup, demo accounts, walkthrough).

## Repository

| Path | What it is |
|---|---|
| `services/core-api` | Python 3.12 · FastAPI · SQLAlchemy · PostgreSQL. A modular monolith with domains (identity vault, customer, need, institution, product, appetite, matching, consent, opportunity, notification, commercial, integrity, intelligence, trust), a persisted graph runtime, a transactional outbox with workers, and an AI Control Plane with deterministic fallback. |
| `apps/web` | Next.js 15 — customer journey, WhatsApp simulator, Institution workspace, WEZA Admin. |
| `apps/mobile` | Flutter customer app (Android and web). |
| `docs/blueprint` | Approved V1 Product, Graph & Loop Architecture Blueprint. |
| `docs/source` | BRD, FSD, TSD and the master engineering skill. |
| `render.yaml`, `apps/web/vercel.json` | Deployment. |
| `.github/workflows/ci.yml` | Lint, security scans, tests, builds. |

## Run locally

```bash
# API (embedded PostgreSQL, migrates and seeds demo data): http://localhost:8000/docs
cd services/core-api && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt pgserver && .venv/Scripts/python scripts/dev_api.py
# Web: http://localhost:3000
cd apps/web && npm install && npm run dev
# Tests
cd services/core-api && .venv/Scripts/pip install pytest && .venv/Scripts/python -m pytest
```
