# Testing WEZA

This guide covers how to get a live link, which demo accounts to use, a 20-minute walkthrough, and what was tested.

> Everything in the demo environment is **fictional**: Lakeside Bank, Pearl SACCO, Kijani Microfinance, Nile Fintech and all customers are made-up demo data. Demo records are marked **Demo** in the institution screens.

---

## 1. Get a live link (one-time, about 10 minutes)

WEZA has two parts: the **API** (Python + PostgreSQL) and the **website** (Next.js). Both deploy straight from this repository.

### Step A: API and database on Render
1. Sign in at <https://render.com> (you can sign in with GitHub).
2. Click **New → Blueprint** and pick the `elijahjb-ai/Weza` repository. Render reads `render.yaml` and creates:
   - `weza-db`, a PostgreSQL database (free);
   - `weza-api`, the API (free). Render generates the secrets itself.
3. Click **Apply**. The first deploy takes about 5–8 minutes. On first start it migrates the database and loads the demo data.
4. Copy the service URL, for example `https://weza-api.onrender.com`. Opening `<that URL>/healthz` should show `{"status":"ok"}`.

> **Free plan behaviour:** the API sleeps after about 15 minutes idle, so the first request afterwards takes about a minute. The free database expires after 30 days. For longer testing, upgrade `weza-api` to **Starter** and the database to a paid plan, or point `DATABASE_URL` at a free [Neon](https://neon.tech) database.

### Step B: Website on Vercel
1. Sign in at <https://vercel.com> with GitHub.
2. Click **Add New → Project** and import `elijahjb-ai/Weza`.
3. Set **Root Directory** to `apps/web`. The framework is detected as Next.js.
4. Under **Environment Variables**, add `API_URL` set to your Render URL from Step A.
5. Click **Deploy**. You get a link like `https://weza-xxxx.vercel.app`. **This is the link to test.**
6. Optional: in Render, set `PUBLIC_WEB_URL` on `weza-api` to the Vercel link, so links in SMS and WhatsApp messages point to it.

### Step C: Android app (optional)
GitHub → **Actions** → latest **CI** run → **Artifacts** → download `weza-android-apk`. Then:
- Unzip it and install `app-release.apk` on an Android phone (allow "install unknown apps").
- The CI build points at `https://weza-api.onrender.com`. If your Render URL is different, go to repository **Settings → Variables → Actions**, add `WEZA_API_URL`, and re-run CI.

---

## 2. Demo accounts

Every staff account uses the password **`WezaDemo!2026`**. In demo mode, the sign-in page also has a **Test accounts** panel that fills them in for you.

| Who | Email | What they see |
|---|---|---|
| WEZA super-admin | `admin@weza.demo` | Network Control Centre, Graph Inspector, kill switches, configuration |
| WEZA operations | `ops@weza.demo` | Institution verification, Human Control Centre, integrity, support lookup |
| WEZA commercial | `commercial@weza.demo` | Disputes, contracts, unit economics |
| Lakeside Bank, administrator | `admin@lakeside.demo` | Activation, users, routing, billing; approves products and appetite |
| Lakeside Bank, executive | `exec@lakeside.demo` | Intelligence only, never customer identity |
| Lakeside Bank, business lead | `business@lakeside.demo` | Product Studio, simulations |
| Lakeside Bank, credit/risk lead | `credit@lakeside.demo` | Appetite Studio, insights, radius |
| Lakeside Bank, team manager | `manager@lakeside.demo` | Feed, team, assignment, customer details for the team |
| Lakeside Bank, officers | `officer@lakeside.demo`, `officer2@lakeside.demo`, `asset@lakeside.demo` | My Day, their own assigned opportunities only |
| Lakeside Bank, compliance | `compliance@lakeside.demo` | Consent and access log |
| Pearl SACCO | `admin@`, `manager@`, `officer@`, `business@`, `compliance@pearl.demo` | Same roles at a SACCO |
| Kijani Microfinance | `admin@`, `manager@`, `officer@`, `officer2@`, `credit@kijani.demo` | Agriculture and solar |
| Nile Fintech (awaiting verification) | `admin@nile.demo` | The onboarding experience before WEZA approval |

**Customers** don't have passwords. They verify by phone. Use any Ugandan-format number, for example `0772 123 456`. SMS isn't connected yet, so in test mode **the 6-digit code is shown on screen** in a gold "Test mode" box. In the WhatsApp simulator it arrives as an SMS bubble.

---

## 3. Walkthrough (about 20 minutes)

### A. Customer (web), the FSD §53 scenario
1. Open the site and type **"I need UGX 30 million to expand my pharmacy"**, then press **Start**.
2. WEZA shows what it understood: amount, purpose, business owner, sector. Tap **Yes, that's right**.
3. Enter a phone number and type the code shown in the Test mode box.
4. Answer the profile questions. Examples: *Grace Nakato*, NIN *CM1234567890AB* (or *skip*), *Nakato Pharmacy*, district *Kampala*, *4 years*, *12 million*, *yes*, *0*, *24 months*.
5. You'll see ranked options with reasons. A match is never presented as an approval. Choose **Lakeside Bank**.
6. Review the consent screen (institution, purpose, exact data categories, version), then tap **I agree**.
7. You get a reference (OPP-…). Open **My requests** to see the status tracker, the Updates tab and the Consents tab, where you can withdraw.

Other things to try:
- **"I need money for school fees"**: WEZA asks only for the missing amount and customer type.
- **"I need UGX 2 billion to build a hotel"**: no institution matches. WEZA explains why and offers the **Waiting Room**.
- Pick an option marked **Needs more info**: WEZA asks for the missing document. Upload any PDF, JPG or PNG under *My documents*.

### B. WhatsApp channel
Open `/whatsapp-sim` (or click *Continue on WhatsApp* on the home page). Enter a number and chat. It runs the **same journey** through the real webhook pipeline. OTP codes arrive as SMS bubbles.

### C. Institution
1. Sign in as `manager@lakeside.demo`. The **Command Centre** opens with a briefing and a "needs your attention" list.
2. Open **Opportunity Feed**. Your new OPP-… opportunity is there, auto-assigned by routing rules.
3. Open it. **Opportunity 360** shows the consented customer details, match breakdown, versions and service target.
4. Click **Mark contacted**. Under **Requests to customer**, click **Ask the customer…** and ask a question or request a document. The customer sees it in *My requests* and can answer there; the answer appears back on the opportunity.
5. Click **Reported approved…**, open **Indicative terms (optional)** and fill in tenor, rate and repayment. Then click **Reported disbursed…**. In the customer's *My requests*, these appear labelled as reported by the institution, with the terms.
6. Sign in as `officer2@lakeside.demo` (or another officer) and open an opportunity assigned to someone else. The customer's identity is **hidden**, because officers only see their own. As `exec@lakeside.demo`, identity is always hidden.
7. As `credit@lakeside.demo`:
   - **Insights** shows an outcome-learning insight: many declines for income/turnover. WEZA recommends a review and never changes rules itself.
   - **Opportunity Radius** shows demand inside, near and outside the appetite. Click **Simulate a change**.
   - **Appetite Studio** has versions, simulation and maker-checker approval.
   - **Sandbox** runs synthetic customers against your configuration.
   - **Ask WEZA**, for example "What sits just outside our appetite?".
8. As `business@lakeside.demo`, create a product in **Product Studio**, or use **Extract from document** with any product PDF or text file. Submit it, then approve as `admin@lakeside.demo`. Approving your own version is blocked (maker-checker).
9. As `admin@lakeside.demo`, open **Billing** and dispute a charge. Then, as `commercial@weza.demo`, open **Disputes** and decide *Charge reversed*. A reversal event is created; history is never edited.

### D. WEZA administration
1. Sign in as `ops@weza.demo`, open **Institutions → Nile Fintech** and **Approve** it. Then sign in as `admin@nile.demo` to see the activation checklist.
2. Sign in as `admin@weza.demo`:
   - **Graph Inspector**: search your OPP-… reference to see customer → need → matches → consent → opportunity → officer → outcome → billing, plus workflow state, events, decisions, audit and AI calls.
   - **Configuration**: toggle **Pause all routing** (with a reason). New customers then see the Waiting Room instead of options. Toggle it back afterwards.
   - **Market State**, **Human Control Centre**, **Loops & AI**, **Audit**.

---

## 4. What was tested

**Automated, on every push** (GitHub Actions, `.github/workflows/ci.yml`):
- **Core API:** 59 tests against a real PostgreSQL database, plus `ruff`, `bandit` and `pip-audit`. Covered:
  - institution information requests (gating, 403 privacy violations, consent scope, expiry, closing on withdrawal, answers saved to the profile with provenance and re-clearing) and indicative terms on approvals;
  - resiliency: audit rows with actor, tenant, action and client IP; MFA for all staff when enforced; notification backoff, dead-lettering and replay; Infobip; k-anonymised preview pass reasons;
  - the full pharmacy scenario end to end, attribution lineage, the versioned snapshot, and idempotent replay (one opportunity, one billing event);
  - OTP failure, lockout and hashing; fact re-use and correction with re-matching; Waiting Room; working without AI;
  - cross-tenant 404s, disclosure by role, assignment and consent withdrawal, preview allow-list, log redaction;
  - append-only audit enforced in the database, the zero-core-integration boundary, rate limits and lockout, the error contract;
  - onboarding through activation, maker-checker, mandatory simulation, k-anonymity, sandbox, role-specific Command Centre, the read-only assistant, outcome insights;
  - outcomes, billing and dispute reversal, product-pause clearing, kill switch, Waiting Room match, rescue with new consent, service-target breach and freshness, the WhatsApp simulator on the same graph;
  - the graph runtime: waits, invalid interrupts, timeouts, ended graphs, step budget.
- **Web:** ESLint (`next/core-web-vitals`), TypeScript check and production build.
- **End-to-end (Playwright, `apps/web/e2e`):** against the API container with demo data. The full E2E-01 happy path: a brand-new institution applies, WEZA verifies it, it's configured and activated, receives a customer's request, asks a question, gets the answer and reports the outcome. An officer works an opportunity in the browser from first contact through an information request, approval with terms and disbursement; the customer answers on *My requests*; executives and other institutions can't see the customer; an institution applies, WEZA verifies it, and its admin reaches the activation checklist.
  - To run locally: start the API (`python services/core-api/scripts/dev_api.py`), then in `apps/web` run `npm run e2e` (first time: `npx playwright install chromium`). Each run starts four customer journeys; the API allows 30 journeys per IP per hour and 20 OTPs per IP per 15 minutes, so clear `platform.rate_counter` in the local database between back-to-back runs.
- **Mobile:** `flutter analyze`, widget tests, APK and web builds.
- **Secret scanning:** gitleaks.

**Manual QA in a browser:** I ran the whole customer journey (intent, confirmation, OTP, profile, options, consent, reference), then the institution steps on that opportunity (assignment, Opportunity 360, contact, approval, disbursement), the Command Centre, Feed, Product Studio, Appetite Studio, Radius, the admin Control Centre, Graph Inspector and Market State. Every institution and admin API endpoint returned 200.

Bugs found during QA and fixed:
- conversation messages could appear out of order;
- quick-reply buttons from an earlier question stayed visible;
- the profile question counter was off by one;
- the conversation was lost if the API was briefly down;
- two grammar slips in the Command Centre briefing;
- demo data aged into "expired".

---

## 5. Connecting real services later (optional)

| To enable | Set on Render (`weza-api`) | Notes |
|---|---|---|
| Full conversational AI | `ANTHROPIC_API_KEY` | WEZA works without it, using structured questions; with a key, understanding of free text improves and **Ask WEZA** gives AI-written answers. |
| WhatsApp Business | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Set the Meta webhook URL to `<API URL>/api/v1/channels/whatsapp/webhook`. |
| Real SMS (OTP and updates) | `SMS_PROVIDER=africastalking` with `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY` (optional `AFRICASTALKING_SENDER_ID`), `SMS_PROVIDER=twilio` with `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM`, or `SMS_PROVIDER=infobip` with `INFOBIP_BASE_URL`, `INFOBIP_API_KEY` (optional `INFOBIP_SENDER`); then `OTP_DELIVERY=sms` | Username `sandbox` uses the Africa's Talking sandbox. Rejected numbers are recorded as failed. With a real provider, one-time codes are not stored. |
| Notification retries | Nothing to set | Failed staff notifications retry with backoff (1 min, 5 min, 15 min, 1 h), then are marked dead and can be replayed from **Events & delivery** in the admin console. |
| Staff email alerts | `SMTP_URL` (`smtp://…:587` STARTTLS or `smtps://…:465` TLS), `SMTP_FROM` | URL-encode special characters in the password. |
| Malware scanning | `MALWARE_SCANNER=clamav`, `CLAMAV_HOST`, `CLAMAV_PORT` | Needs a reachable clamd (for example the `clamav/clamav` container). If clamd can't be reached, uploads are refused, not stored unscanned. |
| Production mode | `ENV=production`, `SEED_DEMO=false`, `DEMO_MODE=false`, `MFA_ENFORCED=true` | The API refuses to start in production and lists what's missing: real secrets, MFA, SMS OTP with a live provider, ClamAV, SMTP, explicit CORS origins. Remaining blockers that config can't check (SSO decision, legal consent text, pen test, DR test) are in [blueprint/13-deployment.md](blueprint/13-deployment.md). |
