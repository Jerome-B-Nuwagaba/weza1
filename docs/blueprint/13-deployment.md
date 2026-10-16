# 13 — Deployment, Environments, CI/CD

## 1. Interim test hosting (Product Owner option a)

| Component | Host | Plan | Notes |
|---|---|---|---|
| Core API (FastAPI) | Render Web Service (Docker) | Free tier to start; Starter ($7/mo) recommended | Free tier sleeps after ~15 min idle, so the first request takes ~1 min |
| Worker | Render Background Worker | Starter (Render has no free workers) | **Fallback if you want $0:** the API runs the worker loop in-process (`RUN_WORKER_INPROCESS=true`). Fine for testing, not for production. |
| PostgreSQL | Render Postgres *or* Neon free | Neon free recommended (Render free Postgres expires after 30 days) | `DATABASE_URL` secret |
| Web (Next.js) | Vercel | Hobby (free) | `NEXT_PUBLIC_API_URL` env |
| Flutter app | GitHub Actions artifact (Android APK) + Flutter web build optional | free | Download from the Actions run / Releases |

**What you will do (one-time, ~10 minutes):**
1. Render → New → Blueprint → select `elijahjb-ai/Weza` → it reads `render.yaml` → set `DATABASE_URL` (Neon) when prompted.
2. Vercel → Add New Project → import `elijahjb-ai/Weza` → root `apps/web` → set `NEXT_PUBLIC_API_URL` to the Render URL.
3. Later: add `ANTHROPIC_API_KEY` (Render env) and WhatsApp credentials (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`). I will tell you exactly when.

Secrets never go in the repository (TSD §69). `.env.example` documents every variable.

## 2. Environments (TSD §80)
LOCAL (docker-compose or native) · DEV (Render preview) · TEST (CI ephemeral Postgres) · UAT/PRODUCTION (Azure, future). Demo data seeding is controlled by `SEED_DEMO=true`, which is never enabled in production. Production data is never copied downward.

## 3. CI/CD pipeline (GitHub Actions)
`commit → lint/format (ruff, eslint, dart analyze) → type-check (mypy, tsc) → unit + graph + integration tests (Postgres service) → security (bandit, pip-audit, npm audit, gitleaks) → build (Docker image, Next.js, Flutter APK) → container scan (trivy) → deploy (Render/Vercel auto-deploy from main) → smoke tests against deployed URL`.

## 4. Azure target (future production; IaC included in `infrastructure/azure`)
Container Apps (api, worker), Azure Database for PostgreSQL Flexible (PITR), Service Bus (topics from §08), Blob Storage (versioning, private endpoints), Key Vault, Entra ID, API Management, Application Insights. RPO 15 min / RTO 4 h proposed for approval. Bicep templates are provided, but they are not deployed in V1-test.

## 5. Production go-live blockers (not needed for testing)
Entra ID / enterprise SSO decision (C5) · approved consent text by legal counsel (Uganda Data Protection and Privacy Act 2019 alignment) · WhatsApp Business verified number · penetration test · DR test.

Built, awaiting accounts: the ClamAV scanner adapter (C7), Africa's Talking and Twilio SMS adapters, and SMTP/SMTPS email. With `ENV=production` the API refuses to start until these are configured, along with real secrets, enforced MFA, SMS OTP delivery and explicit CORS origins (`Settings.production_problems`).
