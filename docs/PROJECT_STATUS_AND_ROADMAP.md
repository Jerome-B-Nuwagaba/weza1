# WEZA — Status Report and Implementation Roadmap

Prepared 13 Oct 2026 · Branch `feature/whatsapp-hardening` (local commits only, nothing pushed) ·
Sources: the BRD, FSD, TSD and Master Skill documents, the repository, and the automated test results.

Legend: **Done** = built and covered by automated tests. **Verified live** = also exercised end to end in a browser on a local
test copy. **Unverified against real Meta** = relies on assumptions about Meta's behaviour that only a real account can confirm.

---

## 1. Executive summary

- WEZA V1's core marketplace is built: customer journey, matching, consent, qualified-opportunity routing, institution
  onboarding, product and appetite studios, the opportunity feed, outcomes, billing and disputes, and admin controls.
- This session hardened the **WhatsApp channel** (status receipts, durable inbound, retries, photos and documents, OTP over
  Meta, config scaffolding), proved that **a brand-new institution can join, go live and receive a WhatsApp customer's
  opportunity**, and added the missing **first-run bootstrap** for real (non-demo) environments.
- Automated tests: **35 at the start of the session → 153 now, all passing** (real PostgreSQL, no real network calls).
- The largest remaining risk is that **nothing has yet run against real Meta**. The next milestone is your own end-to-end test.
- Remaining V1 gaps are production-hardening items (retention, observability, accessibility, uniform rate limits and
  idempotency, a production malware scanner) plus three product decisions (message templates, opt-in policy, localisation).

Rough completion (an estimate, derived from the requirement-by-requirement backlog analysis in `docs/backlog/` plus today's work):
**about 80% of V1 functionality, about 65–70% of production readiness.**

---

## 2. What has been done

### 2.1 Today (WhatsApp, OTP, institution journey) — 10 local commits

| Area | Result | Status |
|---|---|---|
| Config and secrets | `REPLACE_ME` / blank / unset = not configured; app falls back to simulator and never calls Meta or an SMS provider with a placeholder. Safe startup summary (names only). `.env.example` with `>>> USER INPUT REQUIRED:` markers. | Done |
| Setup helper | `scripts/configure_env.py`: hidden-input prompts, writes only the gitignored `.env`, refuses to run if `.env` is not ignored, prints only which names are set. `.gitignore` now covers `.env.*`. | Done |
| Replay helper | `scripts/replay_whatsapp_webhook.py`: signed Meta-style payloads (verify, text, button, duplicate, audio, image, document, statuses, bad signature) against a local API; fake secrets only; refuses non-local URLs. | Done · Verified live |
| Delivery status | `sent → delivered → read / failed` callbacks stored per message (forward-only), Meta message id and error code recorded, journeys never resumed by a status. Migration 0002. | Done · Unverified against real Meta |
| Inbound pipeline | Webhook verifies the signature, stores one deduplicated inbox row per message id, returns 200; the worker processes each number's messages in order. Unsupported types get a polite capped reply; rate-limited or invalid messages are dropped and acknowledged. Fixes the first-message retry bug. Migration 0003. | Done · Verified live |
| Outbound | Failures classified (429/5xx/network retryable, other 4xx permanent), error codes stored, bounded retries (2 resends, 30-minute window), no PII in logs. | Done · Unverified against real Meta |
| Photos and documents | Customers send JPG/PNG/PDF in WhatsApp; downloaded from the Cloud API (https only, size-capped), scanned, stored encrypted, typed from caption/filename or outstanding items, acknowledged; resumes a journey waiting for a missing document. Needs a verified customer. | Done · Unverified against real Meta |
| OTP | `SMS_PROVIDER=whatsapp` sends the code through the Meta API (plain message in-window, or an approved authentication template named by `WHATSAPP_OTP_TEMPLATE_NAME`). Honest failure status; dev mode still shows the code; the code is never stored for real providers. Generic SMS adapter slot kept as a fallback. | Done · Unverified against real Meta |
| Web to WhatsApp | "Continue on WhatsApp" on the landing page and in the chat header; carries the customer's need and campaign/QR reference; API strips it and records attribution. Config-driven number. | Done · Verified live |
| Real-environment bootstrap | `python -m weza.bootstrap` (interactive, or `BOOTSTRAP_ADMIN_*` env vars) creates marketplace config and the first WEZA administrator without demo data; the container start script runs it. | Done · Verified live |
| New institution journey | Join → WEZA verifies → users and teams → product (maker-checker) → appetite (simulate, approve) → routing → notifications → activate → first opportunity from a WhatsApp customer. New automated end-to-end test. | Done · Verified live |
| Onboarding guidance | Activation page shows who can do each step (separation of duties, second approver); appetite empty state explains it. | Done · Verified live |
| Bug fixes | Client-side crash on Notifications, Institution Settings, customer profile and Admin Config pages (an effect returning `null`). A silent "SENT without sending" SMS state now fails honestly. | Done · Verified live |
| Docs | `docs/WHATSAPP.md`: flow, replay, OTP, media, real-environment runbook, Meta test runbook, open decisions. | Done |

### 2.2 Already in the codebase before today (per the spec and the backlog analysis)

Customer journey graph (intent, OTP, dynamic profile, readiness, options, consent), Financial Intent Engine with an AI-off
fallback, deterministic rules and match engine with explanations, market clearing and Waiting Room, qualified-opportunity saga
with idempotent replay, consent ledger and withdrawal, identity vault and role/policy-based disclosure, institution onboarding,
Product Studio (with document extraction), Appetite Studio and simulator, sandbox, routing and service targets, Opportunity Feed
and 360 view, outcome reporting, no-lead and near-match intelligence, opportunity radius, command centre, assistant tools,
notifications with escalation, commercial attribution, billing and disputes, integrity review, admin control centre, graph
inspector, kill switches, Next.js web app, Flutter customer app, CI and Render/Vercel deployment.

### 2.3 Alignment with the BRD / FSD / TSD

In line with the zero-core-integration rule, the funds boundary, the consent-before-disclosure rule, explainable matching and
the five-plane architecture. Accepted deviations (the TSD says "recommended"): Render/Vercel and a Postgres-backed outbox instead
of Azure Service Bus/Redis/API Management; one modular monolith instead of separate services; Flutter instead of React Native.

---

## 3. What is left

### 3.1 Blocked on you (cannot be done without your input)

1. **Real Meta test** — fill the Meta values with `configure_env.py`, expose the API (ngrok/cloudflared), register the webhook,
   and run the journey from your phone. This is the single most valuable next step.
2. **Meta authentication template** — create and get approved in WhatsApp Manager so web-started journeys can receive an OTP
   outside the 24-hour window.
3. **Product/compliance decisions** — see section 5.

### 3.2 Engineering gaps against the specification

| # | Item | Spec reference | Priority |
|---|---|---|---|
| 1 | Retention and privacy lifecycle (retain / archive / delete / anonymise engine) | TSD §70, BRD §38 | P0 |
| 2 | Observability: metrics endpoint, queue-depth and worker health, alerting | TSD §64–65 | P0 |
| 3 | Idempotency keys on every critical endpoint (outcomes, reports) | TSD §60 | P0 |
| 4 | Uniform rate limits (uploads, simulation, AI, institution APIs) | TSD §63 | P0 |
| 5 | Migration guard in CI (single Alembic head; parallel migrations are a known risk) | — | P0 |
| 6 | Production malware scanner (replace the BASIC adapter) | TSD §42 | P1 |
| 7 | Central data classification and enforcement | TSD §49 | P1 |
| 8 | Daily and weekly digests | BRD §21, FSD §34 | P1 |
| 9 | Integrity patterns: abnormal velocity, device and referral signals | TSD §41, FSD §38 | P1 |
| 10 | Accessibility gate (automated plus manual checklist) | BRD §38 | P1 |
| 11 | Entra ID / MFA for institution staff | TSD §13 | P1 |
| 12 | WhatsApp templates (outside the 24-hour window) and opt-in/opt-out handling | — | P1 (needs decisions) |
| 13 | Product-extraction edge cases; admin and institution endpoint regression coverage | — | P2 |
| 14 | Localisation catalogue (English-only today) | TSD §72 | P2 |
| 15 | Mobile release packaging (template TODOs) | — | P2 |
| 16 | Docs/code alignment (`schemas/` folder, platform inbox wording) | — | P2 |
| 17 | Rich status shown to the customer on WhatsApp (delivery state in tracking) | — | P2 |

### 3.3 Known small items from today

- Web "Continue on WhatsApp" starts a fresh WhatsApp conversation seeded with the need; it does not resume the exact web session.
- A status receipt that arrives before the send commits is dropped (rare).
- A crashed processing job can re-send a reply on retry (messages are idempotent, replies are not).
- Raw rule text such as `business_age_months gte 6` is shown on product pages; friendlier labels would help.
- `docs/backlog/` files were included in an earlier local commit by mistake; `apps/web/package-lock.json` has an uncommitted change that is not part of this work.

---

## 4. Verification status

| Check | Result |
|---|---|
| Automated suite | 153 passed, 0 failed (real PostgreSQL, mocked HTTP, fake credentials) |
| TypeScript check | Clean |
| New-institution journey in a browser (clean database, no demo data) | Passed |
| WhatsApp webhook replay (signed payloads, local API) | Passed |
| Real Meta webhook, send, media download, OTP template | **Not yet run** |
| Real SMS gateway | Not applicable (OTP goes through Meta) |

---

## 5. Decisions needed from you / your team

1. Message templates: which messages (waiting-room notices, reminders, status updates), languages, and who owns Meta approval.
2. WhatsApp opt-in and opt-out policy: when consent is captured, how "STOP" is honoured, where it is recorded.
3. Whether digests are V1 or deferred.
4. Minimum retention policy for the test phase versus production.
5. Accessibility standard (for example WCAG 2.1 AA with an automated smoke test).
6. Whether English-only is acceptable for V1.
7. Whether `pip-audit` should fail CI on high/critical findings.
8. Who owns cross-team migration review.

---

## 6. Implementation roadmap

Durations are estimates for a small team and assume decisions in section 5 arrive on time.

### Phase A — Prove it with real Meta (this week)
Goal: the WhatsApp channel works for a real customer on a real number.
- Fill credentials, tunnel, register the webhook, run the journey, upload a photo and a PDF, test an OTP.
- Create and submit the authentication template.
- Triage any Meta-specific differences (payload shapes, error codes) and fix.
- Exit criteria: a real customer completes need → OTP → documents → consent → opportunity visible in an institution's feed.

### Phase B — Production baseline (weeks 1–3)
Goal: safe to run with real customers and real institutions.
- CI migration guard (single head) and a documented migration protocol.
- Idempotency on critical endpoints; rate limits across uploads, simulation, AI and institution APIs.
- Retention and privacy lifecycle baseline (policy-driven, audited).
- Observability minimum: metrics, queue depth, worker health, alerts for dead letters and failed sends.
- Production environment: real WEZA admin via bootstrap, `ENV=production`, `SEED_DEMO=false`, MFA enforced, secrets in the host.
- Exit criteria: P0 items closed, a deployment runbook, a rollback path.

### Phase C — Trust and quality (weeks 3–5)
- Production malware scanner and document pipeline hardening.
- Central data classification; integrity patterns (velocity, device, referral).
- Accessibility pass (axe smoke tests plus a manual checklist on key screens).
- Entra ID / MFA for institution staff.
- Endpoint regression tests for admin and institution APIs; product-extraction edge cases.

### Phase D — Channel completeness (weeks 4–6, after decisions)
- WhatsApp templates and opt-in/opt-out; policy-aware notification routing.
- Daily and weekly digests (if confirmed for V1).
- Delivery state shown to customers; friendlier rule labels in Product Studio.
- Mobile app release packaging.

### Phase E — Pilot (weeks 6–8)
- Onboard two or three real institutions with real products and appetite.
- Run a closed customer pilot through WhatsApp and the web.
- Track the KPIs from the BRD (profile completion, consent rate, time to first contact, qualified opportunities).
- Fix pilot findings; freeze V1.

### Phase F — V1.5 intelligence (after pilot)
- Advanced simulations, demand maps, richer executive briefs, My WEZA customer space, localisation foundation.

### Critical path and risks
- Critical path: Phase A (real Meta) → Phase B baseline → decisions on templates/opt-in → pilot.
- Top risks: Meta behaviour differs from the mocks; template approval lead time; parallel migrations creating multiple heads;
  thin retention/observability before real data arrives; an overloaded single owner for cross-team reviews.
- A seventh role (integrator / QA captain) for 4–6 weeks is recommended by the backlog analysis to protect migration order and
  release quality.

---

## 7. How to run and verify things yourself

```bash
cd C:\Users\LENOVO\weza\services\core-api
.venv\Scripts\python -m pytest -o addopts="" -q        # full suite
.venv\Scripts\python scripts\configure_env.py          # fill real Meta values (hidden input)
.venv\Scripts\python -m weza.bootstrap                 # first WEZA administrator (real environments)
.venv\Scripts\python scripts\dev_api.py                # run the API (restart after code or .env changes)
.venv\Scripts\python scripts\replay_whatsapp_webhook.py list
```

Detailed steps: `docs/WHATSAPP.md`. Requirement mapping: `docs/backlog/02-traceability-matrix.md`.
