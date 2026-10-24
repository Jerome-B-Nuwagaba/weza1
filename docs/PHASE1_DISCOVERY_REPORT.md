# WEZA — Phase 1 Discovery & Plan

**Branch** `test/e2e-integration` @ `a3014bb` (pushed; nothing new committed) · **Date** 2026-10-21
**Scope** Read-only inspection. **No source file was edited.** One diagnostic pytest plugin was written
*outside* the repo (`C:\tmp\cap_probe.py`) to classify the baseline failure; it is not part of the project.

---

## 0. Executive summary

The customer journey the brief describes **is already built and working on this branch**, including the
Just-In-Time credit bureau check. What is missing is not the flow — it is the **evidence**, the **staff
surface**, and **three things that are currently broken or unsafe**.

| # | Finding | Severity |
|---|---|---|
| 1 | **Real Meta + gnuGRID secrets are staged in the git index** in `weza/config.py` (12 secret-bearing fields with hardcoded non-empty defaults). A commit of the current index would publish them. | **Blocker** |
| 2 | **The staged CRB rewrite is broken**: `integrations/gnugrid.py` (5× `F821` on a non-existent `settings`, 3× `F811` redefinition, duplicated `get_crb_client()`), `schemas/crb.py` (breaks `/me/crb` contract), `api/v1/webhooks.py` (dead code, unmounted). 14 ruff errors; **16 of 27 CRB tests fail** on the working tree. | **Blocker** |
| 3 | **The stated success criterion has no test.** CRB coverage is web-channel only; `tests/test_whatsapp_channel.py` (142 tests) contains **zero** CRB references. There is no test that drives first message → profile → consent → mocked CRB → matching → referral → status lookup **over WhatsApp**. | **High** |
| 4 | **Alembic metadata gap → latent `DROP TABLE`.** `weza/models.py` omits `weza.domains.verification.models`. `alembic check` reports `remove_table('customer.identity_check')`. | **High** |
| 5 | **One deterministic baseline test failure**, caused by appetite capacity exhaustion in the test seed — diagnosed below, with a proven fix. | **Medium** |
| 6 | **Staff cannot see any CRB outcome, and no staff list of customer needs/applications exists.** | **Medium** |
| 7 | **The CRB summary never reaches the institution UI** — the API returns it; the page does not render it. | **Medium** |
| 8 | `escalation_sweep` docstring says "then WEZA Ops" but the body only re-notifies institution managers. CRB review kinds are absent from the `ops_alerts` consumer. | **Medium** |
| 9 | Straged file `tatus --short` (a captured `git status` listing) and untracked `services/core-api/.pgdata-fresh/` (a PostgreSQL data dir not covered by `.gitignore`, which only ignores `.pgdata/`). | **Low** |
| 10 | `MAX_INTENT_TURNS = 8` vs blueprint "intent ≤ 6 turns"; CRB consent OTP hardcoded to `channel="sms"` even on WhatsApp; `CONSENT_VERSION` still `2026.10-draft`; stale `docs/CRB_VERIFICATION.md` §3/§4/§6/§7; **zero CRB rows** in `docs/traceability.csv`. | **Low** |

**Baseline measured**: clean `HEAD` → **339 tests, 1 failure**. Clean `HEAD` + capacity isolation → **339 tests, 0 failures**.
(The working tree collects **372** — the extra 33 are the untracked `tests/test_whatsapp_connection.py`.)

---

## A. Architecture and services

A **FastAPI modular monolith** (`services/core-api`, Python 3.12) plus a **Next.js 15 App Router** web app
(`apps/web`), a **Flutter** mobile shell (`apps/mobile`), and a **PostgreSQL 16** database.

| Concern | Location | Size |
|---|---|---|
| API domain code | `services/core-api/weza/` | 15,568 LOC |
| Tests | `services/core-api/tests/` (22 files) | 5,791 LOC / 339 tests |
| Web app | `apps/web/` (84 TS/TSX files) | 11,973 LOC |
| Playwright e2e | `apps/web/e2e/` (6 specs) | 19 tests |
| Mobile | `apps/mobile/lib/` | 6 Dart files, 2 screens |
| Migrations | `services/core-api/migrations/versions/0001…0013` | single head `0013` |

### Domain layout (`services/core-api/weza/domains/`)

`need` (journey + financial need) · `customer` (profile/facts) · `matching` (rules + engine) · `consent`
(consent ledger **+ `crb_service.py`**) · `opportunity` (saga) · `institution` · `product` · `appetite` ·
`trust` (policy/PDP + disclosure gateway) · `integrity` · `notification` · `intelligence` (AI control plane) ·
`verification` (legacy registry) · `commercial` · `identity` (vault, OTP, users).

Cross-cutting: `platform/` (db, events/outbox, graph runtime, crypto, controls, models, logging),
`integrations/gnugrid.py` (bureau client), `api/v1/` (routers), `consumers.py` (24 outbox consumers),
`worker.py` (13 jobs), `seed.py` (demo data).

### Runtime model

- **Graph runtime** (`platform/graph.py`): typed, persisted workflow engine. `MAX_STEPS_PER_ADVANCE = 40`
  (`platform/graph.py:22`). State lives in `platform.graph_instance`; transitions in `platform.graph_transition`.
- **Outbox pattern**: domain writes commit atomically with `platform.outbox_event` rows; `consumers.py`
  registers 24 `@consumer` handlers across 13 topics; `worker.py` runs 13 jobs on a timer.
- **Auth**: customer = phone OTP → session bearer; institution/WEZA = argon2id + TOTP MFA + 15-min JWT +
  rotating refresh cookie. Tenant context comes only from the token.

---

## B. WhatsApp entry points, message state, outbound client, current flow

### Entry points (`services/core-api/weza/api/v1/public.py`)

| Route | Line | Purpose |
|---|---|---|
| `GET /channels/whatsapp/webhook` | 144 | Meta verify challenge (`hmac.compare_digest`) |
| `POST /channels/whatsapp/webhook` | 153 | Signed inbound; HMAC-SHA256 over **raw bytes**; `run_in_threadpool(_ingest_webhook, …)`; returns 200 fast |
| `POST /channels/simulator/messages` | 294 | Simulator → **the same** `inbound()` seam |
| `POST /journeys`, `GET /journeys/{id}`, `POST /journeys/{id}/messages` | 111/122/129 | Web/app journey API |

### The canonical seam — `public.inbound()` (`public.py:227`)

Order of operations, all channel-agnostic:

1. `parse_phone` → `crypto.blind_index("phone", …)`; rate limit `wa:{idx}` (40 / 600 s).
2. Find the open `customer_journey` graph instance by `wa_index`; find the customer by vault blind index.
3. Dedup by provider `message_id` (`ConversationMessage.message_id`).
4. **Commands handled before the graph**: `WITHDRAW` / `CANCEL CONSENT`.
5. **OTP replies route to `CRB_CHECK` first** — even if an older lender has an open question
   (`public.py:250`: `if outputs is None and not (gi and gi.current_node == "CRB_CHECK")`).
6. Otherwise → `journeys.handle_input(db, gi.id, payload, channel="whatsapp", …)`.

### Message-state storage

- `platform.graph_instance` — journey state (`state` JSONB incl. `wa_index`, `channel`, `selected_match_id`,
  `consent_id`, `crb_challenge_id`, `opportunity_id`).
- `ConversationMessage` — canonical transcript, one row per inbound/outbound, `content` JSONB, no plaintext
  phone.
- `whatsapp_inbox` — durable inbound queue (migration 0009/0010): one deduplicated row per provider message id,
  retried with backoff, wiped after processing.
- `Notification` — outbound with `SENT → DELIVERED/READ/FAILED`, `error_code`, bounded retries.

### Outbound client

`notification/service.py:272 _whatsapp_send` → Meta Graph API. ≤3 quick replies become **interactive buttons**
with reply id `f"{action}:{value}"`; >3 falls back to text. Failures classified retryable/permanent;
`UNCERTAIN` (may have reached Meta) is **never resent**. `send_customer_message` (`service.py:73`) routes to
WhatsApp, SMS adapters, or the simulator, and never stores the raw phone (blind index only).

### The current customer flow (graph `customer_journey` v1 — 27 nodes, `need/journey.py:950-964`)

`GREET → UNDERSTAND_INTENT → ASK_INTENT → CONFIRM_INTENT → VERIFY_PHONE → BUILD_PROFILE → ASK_PROFILE →
READINESS_CHECK → (REQUEST_MISSING_ITEM ↺) → PRESENT_OPTIONS → CONSENT → CRB_CHECK → CREATE_OPPORTUNITY →
CONFIRM → TRACKING`, plus `RESCUE_ASK`, `WAITING_ROOM`, `SAVE_EXIT`, `EXPIRE`, `COMPLETE`.

Channel-agnostic: web, app and WhatsApp run the **same graph and the same canonical message contract**.

**Step 10 (status lookup)** exists: `TRACKING` (`journey.py:804`) mirrors institution-reported status; the
customer can return and the same WhatsApp number resumes the same journey. `status_label` (870),
`rescue_ask` (882) handle decline → alternatives.

---

## C. Data model and migrations

13 migrations, single head `0013`. Schemas: `platform`, `customer`, `identity`, `consent`, `need`, `matching`,
`product`, `appetite`, `opportunity`, `institution`, `trust`, `commercial`.

- **Identity vault** (`identity.vault_record`): AES-256-GCM envelope encryption, HMAC-SHA256 blind index for
  phone/NIN. Other domains hold `vault_token` only.
- **Consent ledger** (`consent.consent`): template version, text hash, categories, channel, contact window,
  `granted_at`/`withdrawn_at`.
- **`consent.crb_check`** (migration 0007/0011): the JIT bureau record — consent version + text hash + channel,
  `challenge_id`, `enquiry_id`, `enquiry_reference`, `individual_id`, `status`, `summary` (JSONB), `error_category`,
  `verified_at`. **Never** the NIN, names, photo, addresses or raw bureau response.
- **`customer.identity_check`** (migration 0005) — see finding 4.
- **`appetite.capacity_usage`**: `(appetite_id, window DAY|WEEK|MONTH, window_start, count_used, value_used)`.
- **`opportunity.opportunity`**: `idempotency_key = need_id:match_id`, `integrity_hold`, `state`, `snapshot`.

---

## D. AI components — where they may and may not be used

**One choke point**: `domains/intelligence/ai.py`. Every call goes through `_call()` → `ai_call_log` row, with
`BUDGET_CALLS_PER_SUBJECT = 40` (`ai.py:29`), modes `AVAILABLE | DEGRADED | UNAVAILABLE` (auto-degrades on
error rate), PII redaction (`redact_text`), prompt-injection wrapping (`_wrap`), JSON-schema validation with
**one repair retry**, and a deterministic fallback when AI is unavailable.

**Call sites (exactly three):**

| Site | Purpose |
|---|---|
| `journey.py:133`, `journey.py:235` | `extract_financial_intent` — intent extraction. Deterministic regex parse runs **first**; an explicit number always wins over the AI. |
| `journey.py:390` | `interpret_answer` — interpret a free-text answer to a profile question. |
| `api/v1/institution.py:391` | `extract_product_rules` — product-rule extraction (a **proposal**; a human approves). |

**The boundary holds.** Grepping `matching/`, `opportunity/`, `integrity/`, `appetite/`, `product/` for AI
imports returns **zero**. Eligibility, routing, capacity, integrity scoring and opportunity qualification are
**fully deterministic**: `matching/rules.py` has a closed operator set (`eq/neq/in/not_in/gte/lte/between/
exists/is_true/contains`) and returns `PASS | FAIL | UNKNOWN`; `matching/engine.py` computes
`score = 100 × Σ wᵢ·componentᵢ` with `ALGORITHM_VERSION = "match_v1"` and a `ruleset_hash`. AI-extracted
fields are bounded by enumerated catalogues, capped at `CRITICAL_CONFIDENCE = 0.85`, and require customer
confirmation; `intent_confirmed_at` is hard-required before any opportunity.

**AI must not**: approve/deny credit, override policy, or see bureau data. Verified — no AI call path
receives `crb.*` facts.

---

## E. GNUGrid / CRB status, config, and safe gaps

### Status: implemented and tested offline; **never called live**

`integrations/gnugrid.py` speaks GnuGrid Enquiries API **v1.08**:
`POST /v1/oauth/token` (client credentials, token cached, one refresh on 401) →
`POST /v1/credit-enquiries/request/new` → `POST /v1/credit-enquiries/individual/credit-report`,
reduced to a summary (score, band, adverse accounts, worst arrears, UGX outstanding). The raw report (photo,
contacts, addresses) is never stored or logged. A **mock bureau** answers with the same JSON, so the same
parser runs in CI and on the demo.

### The JIT gate is real and correct

`crb_service._require_selection` (`crb_service.py:123`) gates **every** bureau call behind a SELECTED match
or GRANTED consent for that specific lender. `_crb_check_due` (`journey.py:706`) additionally requires: CRB
enabled, a NIN in the vault, and no reusable result for that lender. The journey node `CRB_CHECK`
(`journey.py:720`) takes a **separate, explicit** consent ("Yes, check" / "No, skip") *after* the sharing
consent — declining skips the bureau and still shares. The legacy capture-time registry call
(`customer/service.py:118`) is dormant (`identity_provider != "gnugrid"`), and there is genuinely **no**
`VERIFY_IDENTITY` node in `need/journey.py`.

### Cost protection (real, and worth keeping)

- One check per customer+ lender at a time (advisory lock **on its own connection**).
- The check row and then the `enquiry_id` are **committed before** the paid report call, so a crash mid-report
  resumes with the paid enquiry instead of paying twice.
- A timeout after sending → `UNCERTAIN` → `CRB_CHECK_UNRESOLVED` review, **never resent**.
- `MAX_NEW_ENQUIRIES_PER_DAY = 3`; results reused for `CRB_FRESH_DAYS = 30`.
- Only identity failures (`MISMATCH`, `NOT_FOUND`) block sharing (`blocks_sharing`, `crb_service.py:425`);
  credit history, ambiguity and bureau outages never do.

### Safe gaps found

1. **Consent text is a draft.** `CONSENT_VERSION = "2026.10-draft"` (`crb_service.py:70`) — needs legal
   approval before live use.
2. **The consent OTP is sent by SMS even on WhatsApp — and the customer cannot act on it.**
   `crb_service.py:177` hardcodes `channel="sms"` even though `issue_consent_otp` accepts a `channel` argument
   (`crb_service.py:146`) and the journey passes the real channel (`journey.py:741`,
   `channel=st.get("channel", "web")`). The customer is told *"Enter the 10-digit WEZA consent code sent to
   {masked} to authorise the credit bureau check"* (`journey.py:743`) — but a WhatsApp-only customer has no
   "application" to enter it in. The `otp_input` card renders **nothing** on WhatsApp: `whatsapp_text`
   (`journey.py:981`) only handles `otp_input` when `dev_code` is present, and `format_for_channel`
   (`journey.py:967`) **strips `dev_code` before the card is persisted or sent**. So in production the customer
   receives a sentence pointing at a code they have no way to reach, and the journey stalls at `CRB_CHECK`.
   Note this is *not* a contradiction of `docs/CRB_VERIFICATION.md` §5: §5 removed the **phone-verification** OTP
   from the WhatsApp chat (the channel already proves phone ownership); this is a different, later
   **lender-consent** code, and §5 does not cover it.
3. **No WhatsApp CRB path at all.** `tests/test_whatsapp_channel.py` has **zero** CRB references; the CRB
   tests (27) are web-channel only. The `CRB_CHECK` node is channel-agnostic in code but has never been
   exercised on WhatsApp, and per #2 it cannot complete there.
4. **Staff have no CRB visibility.** `grep -i crb weza/api/v1/admin.py` → **nothing**. The disclosure gateway
   returns `PERMIT_WITH_RESTRICTED_FIELDS` for *every* WEZA actor (`trust/policy.py:134`,
   reason `weza_staff_use_vault_lookup`), and there is no `crb` permission in `PERMISSIONS`.
5. **The institution UI never shows the report.** `opportunity/service.py:765` puts `credit_report` in the
   customer block when the decision is `PERMIT`; `apps/web/app/institution/opportunities/[id]/page.tsx` renders
   `cust.fields`, `cust.verification.identity` and `cust.documents` — **not** `credit_report`.
6. **The privacy policy never mentions the bureau.** `apps/web/app/legal/privacy/page.tsx` is `IS_DRAFT = true`
   and mentions "credit decisions" only; grep for `bureau|GnuGrid|credit report` → nothing.
7. **CRB review kinds get generic actions.** `apps/web/app/admin/review/page.tsx` `ACTIONS` handles
   `DUPLICATE_HOLD` and `DEAD_LETTER`; `CRB_CHECK_UNRESOLVED`, `IDENTITY_UNVERIFIED` and `CRB_UNAVAILABLE`
   fall through to "Mark resolved" / "Dismiss".
8. **CRB alerts never reach WEZA Ops.** `crb_service._ops_alert` (235) and `_review` (228) create review
   items, but the `ops_alerts` consumer (`consumers.py:230`) subscribes to
   `OpportunityQualified / InstitutionApplicationSubmitted / IntegrityCaseOpened / DisputeOpened /
   OpportunityRoutingFailed` — **no CRB event**.
9. **`escalation_sweep` never escalates to WEZA Ops.** `notification/service.py:510` (`def escalation_sweep`) docstring says "escalate
   to managers, then WEZA Ops (Skill §44)"; the body only calls `notify_institution(..., roles=["MANAGER"])`.
   `notify_weza_ops` exists (426) but is not called from the sweep.
10. **Half-stale documentation.** `docs/CRB_VERIFICATION.md` is accurate at the top — the "Go-live" section
    (line 8, updated 2026-10-18) correctly documents the shipped v1.08 **credit** enquiry/report contract, the
    JIT-only decision and the mock bureau. But **§1–§4 (lines 55–143) are the pre-JIT 2026-10-16 design**:
    §3 (line 83) still documents the v1.08 **KYC** endpoint `/v1/kyc-enquiries/request/new`; §4 (line 91) points
    at `weza/domains/verification/gnugrid.py` (no such file — the client is `weza/integrations/gnugrid.py`) and
    at a `VERIFY_IDENTITY` journey node (line 119) that does not exist (the node is `CRB_CHECK`); §4 (line 140)
    names the table `identity.verification_check` (the real table is `customer.identity_check`); §6 (line 155) uses
    `CRB_BASE_URL` / `CRB_CLIENT_ID` / `CRB_CLIENT_SECRET` / `CRB_PI_CODE` / `CRB_ENQUIRY_REASON` (the code uses
    `GNUGRID_*` / `GNUGRID_ENQUIRY_REASON`); §7 (line 161) references the deleted `tests/test_crb_client.py`.
    `docs/traceability.csv` has 9 rows and **zero** CRB rows.
11. **The `crb.*` facts never reach matching.** `rule_fields` (`customer/service.py:177`) projects no CRB
    field, so a bureau result cannot influence eligibility — consistent with "credit decisions stay with the
    institution", but worth stating explicitly.

---

## F. Institution and staff web workflows + API endpoints

### Institution (`/inst`, `api/v1/institution.py`)

Onboarding (apply → WEZA verify → workspace → users/teams → product → appetite → routing → notifications →
sandbox → activate) · products and appetite studios with maker-checker · the simulator · the **opportunity
feed** (`/institution/feed`, `/my-day`) · opportunity 360 · assignment, status, outcome, info-requests,
documents · previews and interest · intelligence (radius, demand, reason signals, product gaps, insights, ask) ·
reports/outcomes/export · billing · audit · notifications. 28 institution pages under `apps/web/app/institution/`
and 62 routes in `api/v1/institution.py`.

### Staff (`/admin`, `api/v1/admin.py`)

Overview · institutions (list/detail/verify/status) · products and appetites status · market · opportunities ·
**customers/lookup** (audited vault lookup by phone, requires a reason) · review queue · integrity cases ·
disputes · commercial (contracts, unit economics) · graph inspector · audit · deliveries · notifications ·
loops · config (country, consent templates, question paths, match weights, flags, kill switches) · users ·
WhatsApp embedded signup.

### Gaps in the staff surface

- **No staff CRB view at all** (finding E.4), and no permission to express it.
- **No staff list of customer needs or applications** — `/admin/opportunities` lists *opportunities* by
  institution, and `/admin/customers/lookup` requires a phone number. There is no "all customer requests"
  screen, so a customer calling "where is my application?" is looked up by hand.
- `apps/web/app/admin/customers/page.tsx` shows customer KV, needs and opportunities — **no CRB results**.
- `apps/web/app/admin/opportunities/page.tsx` shows reference/institution/amount/need/match/state/owner/age —
  **no CRB status**.

---

## G. Tests, dev commands, deploy config, blockers

### Commands

```bash
# API (services/core-api)
python -m pytest -q -p no:cacheprovider          # 339 tests
python -m ruff check weza tests                   # lint
bandit -q -r weza -x weza/seed.py -s B101,B105,B106,B311,B608
alembic upgrade head                              # migrations
python -m weza.worker                              # background worker

# Web (apps/web)
npm run lint && npm run typecheck && npm run build
npm run e2e                                       # 19 Playwright tests
```

CI (`.github/workflows/ci.yml`): core-api job (ruff, bandit, pip-audit, pytest against a Postgres 16 service),
Docker image smoke test, web lint/typecheck/build, Flutter APK, and a **gitleaks** secret scan.

### Baseline measured on this branch

| Run | Result |
|---|---|
| `HEAD` (clean checkout), full suite, serial | **1 failure** — `test_security.py::test_customers_own_words_are_shown_only_with_permitted_disclosure` → `StopIteration` at `tests/helpers.py:22` |
| Same test **in isolation** | **passes** → order-dependent, not a product defect |
| `HEAD` + per-test capacity isolation | **339 passed, 0 failed** |

**Root cause (diagnosed and proven).** The seeded demo appetite **Q4 SME Growth Mandate** has
`capacity_limits.daily_count = 60` and is *not* reset between tests. The seed creates **25** opportunities
against it; the test suite creates **~35** more. At 60, `capacity_state` (`matching/engine.py:57`) returns
`FULL`, and `evaluate_supply` (`engine.py:163`) then sets `eligible = False`
(`cap not in ("FULL","PAUSED")`) with `capacity_fit = 0.0` — so **Lakeside Bank disappears from the customer's
options**, and `tests/helpers.py:22` (`next(o for o in … if o["institution"] == "Lakeside Bank")`) raises
`StopIteration`. Verified by direct SQL on the post-run database: `fulfilled_count = 60`,
`capacity_usage.count_used = 60`, `capacity_state = 'FULL'`.

**Fix (one line, in `tests/conftest.py`):** reset `appetite.capacity_usage` and the appetite counters between
tests, exactly as `_reset_ip_rate_limits` already does for rate counters. This is a **test-harness** defect,
not a product defect — the product's capacity behaviour is correct.

**Note on the harness:** the session-scoped `database` fixture does `DROP DATABASE IF EXISTS weza_test` +
`CREATE DATABASE weza_test` (`tests/conftest.py:50-70`). **Only one pytest session may run at a time**
against this database — parallel runs destroy each other and produce cascading
`PendingRollbackError` / `OperationalError` failures. (This happened during discovery; the failures were an
artefact of concurrency, not of the code.)

### Deploy config

`render.yaml`: `weza-api` + `weza-db` (free tier; **the free DB expires in 30 days**).
CRB block: `GNGRID_USE_MOCK=true`, `CRB_JIT_ENABLED=true`, `GNUGRID_BASE_URL` / `GNUGRID_CLIENT_ID` /
`GNUGRID_CLIENT_SECRET` / `GNUGRID_ENQUIRY_REASON` / `GNUGRID_PI_CODE` all `sync: false`.
WhatsApp block: `WHATSAPP_TOKEN` / `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_APP_SECRET` / `WHATSAPP_VERIFY_TOKEN` /
`WHATSAPP_BUSINESS_ACCOUNT_ID` / `WHATSAPP_BUSINESS_NUMBER` — all `sync: false`.

### Blockers

1. Secrets in the git index (finding 1).
2. The broken staged CRB rewrite (finding 2).
3. The consent text is a legal draft (E.1).
4. The free Render DB expires in 30 days.
5. The WhatsApp number belongs to another team; the webhook is not pointed at this deployment.

---

## H. Prioritised end-to-end implementation plan

Every step is scoped to files, states the verification, and is a separate commit. **Nothing below has been
started** — this plan awaits your approval.

### Step 0 — Unblock the tree (no behaviour change)

| Action | File |
|---|---|
| `git restore --staged services/core-api/weza/config.py` — the working-tree version already has all secrets as `None`; **the index version has 12 hardcoded credential fields**. No history rewrite needed: the secret-bearing commit `083bffb` is on **no branch** (only agent-checkpoint refs). | index only |
| `git restore --staged services/core-api/weza/api/v1/webhooks.py` — dead, unmounted duplicate of `public.py`; ruff F821/F841/I001 | index only |
| `git restore --staged services/core-api/weza/schemas/crb.py` and `…/integrations/gnugrid.py` — restore the working tree to the clean HEAD versions (the rewrite invents undocumented endpoints `/api/v1/consent/request-otp` and `/api/v1/credit-report/verify`, references a non-existent `settings`, and duplicates `get_crb_client()`) | working tree |
| `git rm --cached -- "tatus --short"` and delete the file | repo root |
| Add `.pgdata-fresh/` to `.gitignore`; never commit `services/core-api/.pgdata-fresh/` | `.gitignore` |
| Re-run: `ruff check weza tests` → clean; `pytest -q` → 339 tests, 1 known failure | — |

**Verification**: `ruff` clean, `pytest` back to the known-good baseline, `git diff --cached` shows no
credential literals.

### Step 1 — Fix the test harness (the baseline failure)

Add a `tests/conftest.py` fixture that clears `appetite.capacity_usage` and resets `fulfilled_count` /
`fulfilled_value` / `capacity_state` for all appetites, mirroring `_reset_ip_rate_limits`.

**Verification**: full suite → **339 passed, 0 failed**, repeatedly and in any order.

### Step 2 — The missing success criterion: a WhatsApp end-to-end test with a mocked CRB

This is the core of the brief. New file `services/core-api/tests/test_whatsapp_crb_e2e.py`, driving the
**signed webhook** (not the simulator), with the offline mock bureau:

1. First WhatsApp message → intent understood → confirm → phone verified **by the channel** (no OTP) →
   dynamic profile (NIN given) → options shown.
2. Select a lender → sharing consent → **separate** CRB consent → bureau result applied.
3. Assert: exactly **one** bureau enquiry; `client_consented == "Yes"`; the enquiry id is recorded; the
   `crb.*` facts carry bureau provenance; the report reaches **that lender only**; another tenant sees nothing.
4. Assert: opportunity created, `OPP-` reference delivered in the chat, and a **later** inbound message
   resumes the same journey and returns the current status.
5. Assert the negatives: declining the CRB check still shares (no bureau call); a bureau outage never blocks;
   an identity failure refuses sharing with a neutral message; a bureau call is **never** made before a lender
   is selected.
6. Assert the WhatsApp-specific behaviours: no OTP code is ever requested or sent on this channel (under
   Option A), `dev_code` is stripped from the persisted outbound message, and no one-time code ever appears in
   the chat text or the stored transcript.

**Depends on the Step 3 decision** (below) for assertion 6.

**Verification**: the new file passes; against the current code it fails (the journey stalls at `CRB_CHECK`) —
that is the point.

### Step 3 — Make the CRB step work **on WhatsApp** (product decision required)

Decision needed from you, then implement. The problem is concrete: on WhatsApp the customer is told to "enter
the 10-digit WEZA consent code", but `format_for_channel` strips `dev_code`, `whatsapp_text` renders no
`otp_input` card without it, and the code was sent by SMS to a number the customer may not have SMS on. The
journey therefore **stalls at `CRB_CHECK`** and the customer never reaches `CREATE_OPPORTUNITY`.

- **Option A (recommended)** — **no code on WhatsApp**; record consent from the explicit "Yes, check" reply
  alone. Rationale: gnuGRID v1.05+ removed its own consent-code methods, and WEZA *already* records the consent
  artefact it needs — `consent_version`, `consent_text_hash`, `consent_channel`, `consented_at` on the
  `crb_check` row (`crb_service.py:162-165`). The signed webhook already proves the customer owns the number,
  which is exactly the argument that removed the *phone-verification* OTP from the WhatsApp chat (§5). The code
  remains for web and app, where a browser session proves nothing.
  *Change*: in `crb_check` (`journey.py:720`), skip the OTP branch when the channel is WhatsApp and go
  straight to `run_check`; keep `issue_consent_otp` for the other channels.
- **Option B** — deliver the code **in the chat** so the customer can reply with it. Keeps the current
  two-factor shape, but the code then proves only possession of the chat, which the signed webhook already
  gives — so it adds friction without adding assurance. Also needs `whatsapp_text` to render the code and
  `format_for_channel` to stop stripping it, which weakens the "no OTP in the transcript" property.
- **Option C** — keep the code on SMS but fix the delivery: honour the `channel` argument in
  `issue_consent_otp` (`crb_service.py:177` hardcodes `channel="sms"`), and change the WhatsApp wording to
  "we've sent a code to your phone". Honest and it works — but it breaks the WhatsApp-only promise, adds an
  SMS dependency, and `render.yaml` has **no SMS provider configured** (`OTP_DELIVERY=display` only), so it
  would fail on the demo today.

Under A: `journey.cr_check` only. Under B: `journey.cr_check` + `journey.whatsapp_text` +
`journey.format_for_channel`. Under C: `crb_service.issue_consent_otp` + `journey.cr_check` wording.
The inbound routing already special-cases `CRB_CHECK` (`public.py:250`), so an OTP reply reaches the node.

**Also in this step**: `MAX_INTENT_TURNS = 8` → **6** to match `docs/blueprint/05-graphs.md:48` and
`06-loops.md:70` (both state 6).

### Step 4 — Staff visibility for CRB (needs your decision on scope)

- **Option A (recommended)** — a **narrow, audited** staff capability: WEZA Ops/Compliance can see the CRB
  **outcome status** (VERIFIED / NOT_FOUND / MISMATCH / AMBIGUOUS / UNRESOLVED / never checked) and a
  **summary** for a customer **they are already supporting** (i.e. behind the existing audited
  `customers/lookup` with a reason), plus the CRB review queue. Requires: a new `crb.read` permission in
  `trust/policy.py` `PERMISSIONS`, a decision branch in `_decide` for a *specific* resource (not a blanket
  staff override), a new audited route, and the same treatment in `apps/web/app/admin/customers/page.tsx`.
- **Option B** — staff see only the **status**, never the report. Simpler and lower risk; keeps the report
  institution-only.
- **Option C** — leave staff without CRB visibility and rely on the institution + the review queue.

I would implement **A** with a `crb.read` permission gated to `WEZA_OPS` / `COMPLIANCE` / `WEZA_SUPER`,
behind the existing audited-reason lookup, with every access written to `trust.audit_event` and
`policy.decision_log`. **This touches `api/v1/admin.py` and `apps/web/app/admin/*`, which the recorded scope
says another person owns** — so I need your explicit instruction before I write there, and can otherwise
deliver the API and leave the staff page to the other owner.

### Step 5 — Institution sees the credit summary (in my scope)

`apps/web/app/institution/opportunities/[id]/page.tsx` already receives `cust.credit_report` from
`GET /inst/opportunities/{id}`; it is simply not rendered. Add a card showing the report with
`REPORT_LABEL` ("WEZA does not make credit decisions — your institution performs its own KYC and
underwriting") and the `pulled_at` timestamp. Also show the CRB status in the feed card when present.

**Verification**: extend `tests/test_gnugrid_integration.py` (or the new Step 2 file) to assert the shape the
page consumes, plus a Playwright check on the opportunity page.

### Step 6 — Escalation and review-queue correctness

- `notification/service.py:510 escalation_sweep` — make it escalate to **WEZA Ops** (via `notify_weza_ops`)
  after the institution-manager step, as the docstring already promises.
- `consumers.py:230 ops_alerts` — include the CRB failure events so a `CRB_UNAVAILABLE` / `CRB_CHECK_UNRESOLVED`
  reaches WEZA Ops, not only the review queue.
- `apps/web/app/admin/review/page.tsx` `ACTIONS` — give the CRB kinds meaningful actions
  (e.g. "Re-run check" / "Accept and continue" / "Contact customer"), instead of the generic
  resolve/dismiss. *(staff page — subject to the Step 4 scope decision)*

### Step 7 — Documentation and traceability

- Rewrite `docs/CRB_VERIFICATION.md` §3/§4/§6/§7 to the **shipped** v1.08 credit-enquiry contract, the real
  file paths (`weza/integrations/gnugrid.py`, `weza/domains/consent/crb_service.py`, node `CRB_CHECK`), and the
  real setting names (`GNUGRID_*`).
- Add CRB rows to `docs/traceability.csv` (requirement → test evidence).
- Add the bureau to `apps/web/app/legal/privacy/page.tsx` (it is `IS_DRAFT = true`): who is checked, what is
  stored, the 30-day reuse window, the 3-per-day enquiry cap, and that WEZA makes no credit decision.
  *(legal page — flag for the other owner if it is out of my scope)*

### Step 8 — Close the Alembic metadata gap

Add `from weza.domains.verification import models as _verification` to `services/core-api/weza/models.py`.

**Why it matters**: `alembic check` currently reports
`remove_table('customer.identity_check')` — a future `alembic revision --autogenerate` would emit a migration
that **drops the identity-check table** (and its index), losing real data. Verified by running `alembic check`
against the migrated database.

**Verification**: `alembic check` → "No new upgrade operations detected".

### Step 9 — Repo hygiene

- `services/core-api/.pgdata-fresh/` → add to `.gitignore` (alongside `.pgdata/`).
- `services/core-api/scripts/connect_whatsapp_webhook.py` and
  `services/core-api/tests/test_whatsapp_connection.py` (both untracked, both passing ruff) — commit them
  with the `docs/WHATSAPP_GO_LIVE.md` and `render.yaml` changes, **after** the other owner's WhatsApp work is
  confirmed as complete (they touch the WhatsApp channel, which is out of my scope).

---

## What I need from you

1. **Approve the plan** (or tell me which steps to run).
2. **Step 3 decision**: how should the CRB consent code reach a WhatsApp customer? (A: no code on WhatsApp ·
   B: send the code in the chat · C: keep it on SMS but fix the channel). I recommend **A** — the channel is
   already signature-verified, gnuGRID v1.05+ removed consent-code methods, WEZA already records consent
   version/text-hash/channel/time, and today the code is unreachable by a WhatsApp-only customer.
3. **Step 4 decision**: should WEZA staff see CRB outcomes, and at what granularity? I recommend **B or A**,
   behind the audited support lookup. This needs your explicit go-ahead because it touches
   `api/v1/admin.py` and `apps/web/app/admin/*`, which another person owns.
4. **Step 0 handling**: may I unstage the four index entries and restore the working-tree CRB files to HEAD?
   This is what removes the secrets from the commit path.

**Explicitly out of my scope, unchanged by this plan**: `apps/web/app/admin/*`, `api/v1/admin.py`,
`public.py`'s WhatsApp webhook/simulator, `_whatsapp_send`, `apps/web/app/whatsapp-sim` — unless you say
otherwise. Steps 4, 6 (review page), 7 (privacy page) and 9 touch those; I will implement the API side and
hand the pages over, or wait for the other owner.
