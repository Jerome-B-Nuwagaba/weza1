# Connecting the organisation's existing WhatsApp Business number — status and go-live

## Hosted cutover — 2026-10-19

The public `https://weza-api.onrender.com/healthz` was checked again on 2026-10-19 and returned
**Service Suspended**. The callback last recorded below points to ngrok on a laptop. The current Meta callback
and Render settings cannot be established from Git; inspect them in the owning accounts before declaring this live.

The branch now prepares an always-on Render web service (`starter`, a paid instance), explicitly deploys
`test/e2e-integration`, runs its inbox/outbox worker inside the API, and uses `/readyz` to check PostgreSQL and
the worker thread. `WHATSAPP_REQUIRED=true` refuses startup when any of the four essential channel secrets/IDs
is missing instead of silently writing simulator replies. These repository changes do not unsuspend a service,
change its billing plan, upload credentials or update Meta's callback by themselves.

To finish the cutover in the hosting accounts:

1. Restore the suspended Render service. Confirm its repository branch is `test/e2e-integration`. Select an
   always-on instance; applying the prepared `starter` plan incurs Render charges. Keep `RUN_WORKER_INPROCESS=true`.
2. Put the existing permanent `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` and
   `WHATSAPP_VERIFY_TOKEN` in **Render environment settings**, along with `WHATSAPP_BUSINESS_ACCOUNT_ID` and
   `WHATSAPP_BUSINESS_NUMBER`. Local `.env` files are not uploaded by the Docker build.
3. Use a persistent PostgreSQL database. The prepared Blueprint selects paid `basic-256mb`; free databases expire
   after 30 days. Upgrade the existing database or set `DATABASE_URL` to a persistent hosted database. Preserve the
   existing vault/blind-index keys so existing customer data remains readable.
4. Deploy this branch and require `GET <actual Render API URL>/readyz` to return 200. Inspect Render logs for
   `worker_started`. A healthy process cannot establish Meta delivery or permissions on its own.
5. In Meta → WhatsApp → Configuration, replace the **ngrok callback** with
   `<actual Render API URL>/api/v1/channels/whatsapp/webhook`, using the same verify token as Render. Subscribe
   `messages` and `account_update`. Confirm the app remains subscribed to the correct WABA. Run
   `python scripts/whatsapp_account_check.py` in the hosted environment to inspect token, number and callback.
6. With local API/tunnel processes stopped, send a new message from a test customer's WhatsApp. Confirm Render
   logs show `whatsapp_webhook`, an inbox row completes, and an outbound Meta message is delivered. Repeat after
   20 minutes idle and after a Render restart. No laptop process should be needed.

**CRB:** the shared WhatsApp journey includes lender selection → separate bureau consent → a 10-digit consent
code → the gnuGRID enquiry/report. WhatsApp now sends this code through the WhatsApp channel; web/app journeys
continue through SMS. Automated tests exercise signed webhooks with a fake Meta sender and offline bureau, including
consent refusal. This verifies application wiring, not the live bureau account. The Blueprint is still deliberately
`ENV=dev` / `GNGRID_USE_MOCK=true`: it does **not** establish a real gnuGRID connection. Real calls require
`ENV=production`, `GNGRID_USE_MOCK=false`, `IDENTITY_PROVIDER=gnugrid`, real `GNUGRID_*` credentials and all production
prerequisites described in [CRB_VERIFICATION.md](CRB_VERIFICATION.md). Check authentication in the hosted environment
with `python scripts/crb_connection_check.py` (no enquiry or customer data). Run a real paid enquiry only with an
authorised applicant's explicit consent; never use one as a connectivity probe.

The historical checkpoint below describes the earlier local setup and is not a current live verification.

Validation for this change: 187 tests passed across `test_whatsapp_channel.py`, `test_gnugrid_integration.py`
and `test_whatsapp_onboarding.py`; Ruff passed for `weza` and `tests`. The new tests run an actual in-process
worker without manually draining events and drive signed WhatsApp webhooks through lender consent, WhatsApp
code delivery, bureau consent/refusal and submission. Meta and the bureau are fake in these tests. No live
customer message or paid enquiry was sent, and no Render/Meta settings were changed.

Checkpoint document for connecting the existing number to the WEZA agent. It records what was verified, what the code
now does, the coexistence plan, the Meta-side steps, and the live acceptance checklist. The historical local setup
below is separate from the Render connection. **The Render WhatsApp connection is pending verification.**

## Current branch target (2026-10-20)

The API target for `test/e2e-integration` is `https://weza-api-go6e.onrender.com`. Configure the existing Cloud API
number with this callback:

```text
https://weza-api-go6e.onrender.com/api/v1/channels/whatsapp/webhook
```

1. Deploy this branch to that existing Render service. Set `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
   `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_BUSINESS_NUMBER` and
   the verified `WHATSAPP_API_VERSION` in Render's environment. Use the existing Meta app and number; no new number
   registration or Embedded Signup is required. Keep credential values out of source control and logs.
2. Keep `RUN_WORKER_INPROCESS=true`, as in `render.yaml`, or run `python -m weza.worker` separately against the same
   database. The API saves incoming messages immediately; the worker advances the existing customer journey and
   sends replies. Container startup runs database migrations before serving requests.
3. Before switching Meta's callback, check `/healthz` and `/api/v1/health`, then verify the callback handshake:
   GET the callback with `hub.mode=subscribe`, `hub.verify_token` set from the configured secret and a chosen
   `hub.challenge`. Expect HTTP 200 with the exact challenge; a wrong token must return 403. Load secrets locally
   without printing them or putting them in shell history.
4. Check signature validation without creating a customer or sending a message: POST the exact UTF-8 bytes of
   `{"object":"whatsapp_business_account","entry":[]}` with `Content-Type: application/json` and
   `X-Hub-Signature-256: sha256=<hex HMAC-SHA256 of those bytes using WHATSAPP_APP_SECRET>`.
   Expect HTTP 200 and `{"ok":true}`; missing or incorrect signatures must return 403. This empty event validates
   configuration only; it does not prove delivery or worker processing. The local replay helper intentionally
   refuses public URLs and must not be used for this preflight.
5. In the existing Meta app, set the callback above and the matching verify token, subscribe to `messages` and
   `account_update`, and confirm the app is subscribed to the existing WABA. Re-run
   `scripts/whatsapp_account_check.py` with the same configuration to inspect the callback, subscription and token.
6. From a phone you control, message the business number with a financing request. Confirm one inbox record reaches
   `DONE`, the reply reaches the phone, and delivery receipts reach `delivered`/`read`. Continue the conversation and
   confirm answers update the same journey and its system records. Use the acceptance checklist in §7 to record
   the result before marking the Render connection live.

An HTTP health response, configured credential flags or a successful handshake alone does not establish a live
WhatsApp connection. `AI mode: UNAVAILABLE` still permits the existing deterministic journey to collect information
and reply; configuring `ANTHROPIC_API_KEY` enables the optional conversational AI. The Render free plan can sleep,
so continuous low-latency replies need an always-on service. A paid-plan change is a separate hosting decision.

## 1. Historical verified status (2026-10-16; local API behind ngrok)

| Item | Status | How it was established |
|---|---|---|
| `services/core-api/.env` WhatsApp values | Present: token, phone number ID, WABA ID, app ID, app secret, verify token, business number, OTP template, API version v26.0 | key names checked; values never printed |
| Access token | **Permanent System User token** (`weza-api`, never expires), assigned to the WhatsApp Business Account | `whatsapp_account_check.py` |
| `WHATSAPP_APP_SECRET` | **Correct** (replaced 2026-10-16; Meta accepts it) | `appsecret_proof` check |
| The organisation's number (…258, "Otic Weza") | **Already registered on Cloud API**: `platform_type=CLOUD_API`, `status=CONNECTED`, `account_mode=LIVE`, `code_verification_status=VERIFIED`, `is_on_biz_app=false`; display name `PENDING_REVIEW`. It is the customer-facing number and matches `WHATSAPP_BUSINESS_NUMBER` | `whatsapp_account_check.py` |
| WhatsApp Business Account | "Otic Weza", ownership SELF, account review APPROVED, business verified; this app is subscribed to its webhooks; templates `weza_otp` (AUTHENTICATION, en) and `hello_world` approved | `whatsapp_account_check.py` |
| Webhook | Meta's callback points at a developer's ngrok tunnel → local API :8000, field `messages` only (add `account_update`). Through that URL: handshake OK, wrong token 403, signed POST 200, bad signature 403 | webhook check through the public URL |
| Live round trip (2026-10-16) | **Working** with the dev setup: a customer message reached WEZA, the agent replied from …258, and receipts came back `delivered` | inbox + `channel_message` records |
| Lessons from going live | (1) Use a **System User** token (an employee system user is enough). (2) Assign it to the **WhatsApp Business Account** itself; the "WhatsApp business presence" on Meta's new settings screen has a different ID, and assigning only that gives error 10 *"Viewer cannot access the provided Paid Message Account"* when sending (`scripts/whatsapp_owner_check.py` shows this). (3) Add a payment method. (4) Start the API from a window **without** the fake replay values (`set WHATSAPP_…=FAKE_…`): environment variables override `.env`, and every real webhook then fails with 403 | diagnosed live |
| Hosting | Development only: a local API behind ngrok. `https://weza-api.onrender.com` answers *503 Service Suspended* | public `GET /healthz` |
| Integration path | **Direct Cloud API.** The number is already on Cloud API, so coexistence, Tech Provider approval and Embedded Signup are **not needed for …258**. §2–2a only apply to a number still in the WhatsApp Business app | account check, confirmed with you |
| Graph API version | Code default raised from v21.0 (expires 2027-01-21) to v25.0 (supported until 2028-07-29); `.env` uses v26.0 | Meta versions page |

## 2. Integration path — coexistence (decided 2026-10-16)

> **Update 2026-10-16:** the customer-facing number …258 turned out to be **already on Cloud API** (§1), so this
> section and §2a don't apply to it. Keep them for any number that is still in the WhatsApp Business app. For …258
> only §3 steps 5–12 remain: permanent token, webhook fields (`messages`, `account_update`), hosting and templates.

**Decision:** keep the number in the WhatsApp Business app and connect WEZA to it through the Cloud API
(*coexistence*), onboarded with Embedded Signup. Migration (deleting the account from the app and moving the number to
Cloud API only) was **not** chosen and won't be done.

What coexistence means (Meta, *Onboard WhatsApp Business app users*):
- The phone that holds the number must run WhatsApp Business app **2.24.17 or newer**.
- **Embedded Signup run by a Tech Provider or Solution Partner app** is the only way in. Use Embedded Signup v4;
  v2 was deprecated on 2026-10-15.
- Throughput is fixed at 20 messages/second. In the app, group chats aren't synced and broadcast lists become
  read-only. Disappearing messages, view-once, live location, calls, catalog/status and channels aren't supported.
  Companion devices are unlinked at onboarding; up to 4 can be relinked, but WhatsApp for Windows/WearOS can't.
- Staff messages from the app stay free; WEZA's Cloud API messages are billed at Cloud API rates.
- **The connection can drop without anyone touching WEZA.** Staff can press *Settings → Account → Business Platform
  → Disconnect*; re-registering or moving the phone offboards it; and Meta disconnects for inactivity
  (`PRIMARY_INACTIVITY`, `COMPANION_INACTIVITY`). WEZA now turns these `account_update` webhooks into a HIGH
  `WHATSAPP_DISCONNECTED` review item (§6). Keep the phone with the app switched on and in regular use.
- Every message staff send from the app arrives as `smb_message_echoes`. WEZA acknowledges it and never routes it
  to the agent.

### 2a. Coexistence plan

**Phase 0 — credentials (you, now).**
1. Meta app → App settings → Basic → copy the real *App secret* (32 hex characters) → `WHATSAPP_APP_SECRET`.
2. Business Settings → Users → *System users* → add an Admin system user → *Assign assets*: the Meta app (full
   control) → *Generate token* with `whatsapp_business_messaging` + `whatsapp_business_management`, expiry *Never*
   → `WHATSAPP_TOKEN`. If the organisation's number has no WhatsApp Business Account in your portfolio yet, the WABA
   is created during onboarding (Phase 2). Then assign it to the same system user; the token keeps working.
3. Run `scripts/whatsapp_account_check.py`. Expected now: token valid with no expiry, and *App secret belongs to the
   token's app: True*. The number fields show whether the configured `WHATSAPP_PHONE_NUMBER_ID` is a Meta test number.

**Phase 1 — become able to run Embedded Signup (you; Meta review time not documented).** A1 was chosen; A2 stays the fallback:
- **A1, your own app as Tech Provider (chosen 2026-10-16).** Steps:
  - Complete Meta *business verification* for the portfolio (name, address, phone, email, website, documents).
  - Pass *App Review* with two screen recordings: a message sent from the app and received in WhatsApp, and a
    template being created. The API Setup cURL and WhatsApp Manager recordings are accepted alternatives.
  - Request *Advanced access* for `whatsapp_business_messaging` and `whatsapp_business_management`. Meta's guide
    requires this before onboarding *clients*; ask Meta support whether Standard access is enough when the only
    WABA onboarded is your own.
- **A2, an existing Meta Solution Partner that offers coexistence onboarding.** Faster if A1 stalls. Before
  signing, confirm in writing that your own Meta app's system user can send messages and receive the webhooks for the
  WABA after onboarding. Otherwise WEZA would have to call the partner's API instead, which isn't built.

**Phase 2 — Embedded Signup set-up and onboarding (A1, chosen 2026-10-16; WEZA side built).**
1. App Dashboard → *Facebook Login for Business* → create a configuration with the *WhatsApp Embedded Signup* login
   variation. Select the WhatsApp Cloud API and *WhatsApp Business app user onboarding* products; choosing products
   puts the configuration on v4. Note the configuration ID → `WHATSAPP_EMBEDDED_SIGNUP_CONFIG_ID`.
   App settings → Basic → *App ID* → `WHATSAPP_APP_ID`. Neither is a secret.
2. In *Client OAuth settings*, enable *Login with the JavaScript SDK* and *Enforce HTTPS*. Add the WEZA web domain
   (HTTPS) to *Allowed domains* and *Valid OAuth redirect URIs*. Embedded Signup won't open from `http://localhost`.
3. Restart the API. In the WEZA web app, sign in as a **WEZA super-admin** (MFA step-up applies when enforced) →
   *Inspect → WhatsApp connection* → **Connect WhatsApp Business app number**. Behind the button:
   - The page loads Facebook's JS SDK and calls `FB.login` with the configuration ID, `response_type: "code"` and
     `extras: {setup: {}, featureType: "whatsapp_business_app_onboarding", sessionInfoVersion: "3"}`.
   - It listens for `WA_EMBEDDED_SIGNUP` window messages, accepting only `facebook.com` origins; success is
     `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` with `waba_id`.
   - The one-time code goes straight to `POST /api/v1/admin/whatsapp/embedded-signup` (it expires in ~30 s). The
     server exchanges it (`GET /oauth/access_token` with the app ID and app secret) and checks the WABA was granted
     to this app (`debug_token`). It then subscribes the app to the WABA's webhooks (`POST /<WABA_ID>/subscribed_apps`)
     and reads the WABA's numbers with `is_on_biz_app`/`platform_type`.
   - The business token is used only during that request: never stored, logged or returned. The action is audited
     as `whatsapp.embedded_signup`, with no token.
   - The page shows the `WHATSAPP_BUSINESS_ACCOUNT_ID` and `WHATSAPP_PHONE_NUMBER_ID` to set, plus any warnings.
4. On the day, someone holding the phone (app updated) runs the flow and enters the code WhatsApp shows in the app.
   **Phone-number registration is skipped**: the number is already registered, and registering would be wrong for
   coexistence. WEZA never calls the Register API.
5. Not verified against real Meta yet: the `featureType`/`sessionInfoVersion` launch options come from Meta's
   coexistence guide. On the first real run, confirm the account screen offers connecting an *existing WhatsApp
   Business app* account. If it doesn't, check the configuration's products before changing code.
6. Within 24 h of onboarding Meta allows a one-time contacts/history import (`POST /<PHONE_NUMBER_ID>/smb_app_data`).
   **Recommendation: don't request it.** WEZA doesn't need up to 180 days of past chats, and not importing them
   avoids storing personal data with no purpose. Requesting it later means offboarding and onboarding again.

**Phase 3 — wire WEZA to the connected number (you, then a check).** Do steps 3–4 and 6–11 of §3 with the new IDs.
Webhook fields: `messages` and `account_update`; `smb_message_echoes` is optional and harmless. Then
`whatsapp_account_check.py` must show the organisation's number with `is_on_biz_app=true` and
`platform_type=CLOUD_API`.

**Phase 4 — go live.** Decide the hand-over rule (below), deploy (§5, with your approval), and run the acceptance
checklist (§7) including checks 10–11.

**Still open (your decisions):**
- **Hand-over.** Staff in the app and the WEZA agent will both answer the same customer. Choose a rule, for example
  "pause the agent for 12 h for a customer after a staff reply" or "staff never reply to customers WEZA is serving".
  It isn't built.
- **Templates** for messages sent more than 24 h after a customer's last message (§6).

## 3. Meta-side checklist (you)

Collect the following into `services/core-api/.env` (or the hosting provider's secret settings) with
`python scripts/configure_env.py`. Never paste them into chat, tickets or git.

1. **Business Portfolio**: Meta Business Settings → note the portfolio that owns the number. Complete *Business
   verification* if it's not done (needed for Tech Provider/App Review and higher messaging limits).
2. **Onboard the number with coexistence** (§2a, Phases 1–2): Embedded Signup, then enter the code shown in the
   WhatsApp Business app. Don't use WhatsApp Manager → *Add phone number*: that is the migration path.
3. **WABA ID**: WhatsApp Manager → Account tools → *WhatsApp Business Account ID* → `WHATSAPP_BUSINESS_ACCOUNT_ID`.
4. **Phone number ID** of the organisation's number (not the test number): Meta app → WhatsApp → API Setup → *From*
   → choose the real number → copy the ID → `WHATSAPP_PHONE_NUMBER_ID`. Set `WHATSAPP_BUSINESS_NUMBER` to the same
   number (digits with country code).
5. **Permanent token**: Business Settings → Users → *System users* → add (Admin) → *Assign assets*: the Meta app (full
   control) and the WABA (full control) → *Generate token* for the app with `whatsapp_business_messaging` and
   `whatsapp_business_management`, expiry *Never* → `WHATSAPP_TOKEN`.
6. **App secret**: Meta app → App settings → Basic → *App secret* (32 hex characters) → `WHATSAPP_APP_SECRET`.
7. **Verify token**: any long random string you choose → `WHATSAPP_VERIFY_TOKEN`.
8. **API version**: leave `WHATSAPP_API_VERSION` at v25.0 or v26.0.
9. Run `python scripts/whatsapp_account_check.py` and check: token valid with no expiry, app secret matches,
   number = the organisation's number, `platform_type=CLOUD_API`, `code_verification_status=VERIFIED`.
10. **Public HTTPS endpoint** (§5) running the API with these values. Then in the Meta app → WhatsApp →
    Configuration → Webhook: callback URL `https://<host>/api/v1/channels/whatsapp/webhook`, verify token from
    step 7 → *Verify and save*, then **subscribe the `messages` field**. (For coexistence, also subscribing
    `smb_message_echoes` is harmless: WEZA acknowledges and ignores it.) **Also subscribe `account_update`**, so that
   WEZA raises an alert when the number is disconnected.
11. **Subscribe the app to the WABA** if the check script shows no subscribed apps:
    `POST /<WABA_ID>/subscribed_apps` with the system-user token (Embedded Signup partners usually do this). This
    changes Meta configuration, so it is listed here for you; it was not run.
12. Optional but needed for messages more than 24 h after the customer's last message (status updates, reminders):
    approved **message templates** (§6).

## 4. Read-only account check

    cd services/core-api
    .venv\Scripts\python scripts\whatsapp_account_check.py

It sends only GET requests. It prints the token type, expiry and scopes, whether the app secret matches the token's
app, and the number's registration and coexistence status (`is_on_biz_app`, `platform_type`). It also shows the
WABA's numbers, subscribed apps, templates and the app's webhook callback URL and fields. Phone numbers are masked;
the token and secret are never printed.

The connection helper checks the target API against the same local settings before changing Meta. From
`services/core-api`, inspect the plan first:

```powershell
.venv\Scripts\python scripts\connect_whatsapp_webhook.py --api-base-url https://weza-api-go6e.onrender.com
```

It checks API/database health, outbound readiness, the business number, good and bad verification tokens and
signatures, the Meta token/app secret, WABA ownership, and existing callback overrides. Its only API POST probes
contain an empty webhook; no customer message is created or sent. It reports safe check names and proposed changes.
With the Render environment ready, apply the checked connection:

```powershell
.venv\Scripts\python scripts\connect_whatsapp_webhook.py --api-base-url https://weza-api-go6e.onrender.com --apply
```

`--apply` preserves existing WhatsApp subscription fields, adds `messages` and `account_update`, updates the app's
callback, and subscribes the app to the WABA only if absent. Conflicting WABA/phone callback overrides stop the
operation for review. Meta changes are read back before reporting `connected`; `attempted` and `applied` distinguish
an uncertain/partial update from a completed one. This verifies configuration, not customer delivery: keep the worker
running and complete the live acceptance checklist below.

## 5. Hosting the webhook

The API must be reachable over public HTTPS with a valid certificate. Options:
- **Render** (`render.yaml`): fill the `WHATSAPP_*` variables in the Render dashboard. The free plan sleeps after
  ~15 min idle, and the first webhook after sleeping can take about a minute. Meta then retries, and WEZA
  deduplicates those retries, but replies are slow. The current branch targets `weza-api-go6e.onrender.com`;
  follow the current-target section above. The older suspended URL in §1 is historical.
- **Temporary test**: run the API locally and expose it with `ngrok http 8000` or
  `cloudflared tunnel --url http://localhost:8000`.
- Keep `RUN_WORKER_INPROCESS=true` (or run `python -m weza.worker`): without the worker, messages are stored but
  never answered.
- Record deployment and callback verification against the current target; the historical ngrok result does not
  establish readiness on Render.

## 6. What the code does now

```
Customer → Meta → POST /api/v1/channels/whatsapp/webhook
  verify X-Hub-Signature-256 (app secret, constant-time) ─ invalid → 403
  only change.field == "messages" for OUR phone_number_id (echoes/history/other numbers ignored, still 200)
  statuses → delivery receipts on notification.channel_message (sent → delivered → read, never backwards)
  messages → notification.whatsapp_inbox (unique per wamid: Meta retries are no-ops), encrypted payload, outbox event
  → 200 immediately
Worker → per-number advisory lock → pending messages oldest first
  → public.inbound() → existing customer-journey agent (need.service.handle_input → graph → AI control plane with
    deterministic fallback → matching/consent/opportunity services)
  → replies via notification.send_customer_message() → Cloud API /<PHONE_NUMBER_ID>/messages
```

Failure handling added in this change:
- **Processing errors**: only the failing message is rolled back. It is retried at 30 s and 60 s; later messages from
  the same customer wait behind it so the order is kept. After 3 attempts it is marked FAILED and the customer gets
  *"Sorry, something went wrong…"*. An operations review item (`WHATSAPP_INBOUND_FAILED`) is raised, and the number is
  unblocked. A message whose queue event was lost is picked up by the 30 s sweep after 2 min.
- **No duplicate replies**: if a reply already went to Meta before the error, the message isn't retried
  (`PARTIAL_REPLY`).
- **Outbound outcomes**: `SENT` means Meta accepted the request; delivery is confirmed only by the `delivered`/`read`
  status webhooks. A timeout after sending is recorded as `UNCERTAIN` and never re-sent automatically. Connection
  failures, rate limits (130429, 131056, 131048, 80007, 4) and Meta server errors are retried twice within 30 min.
  Invalid recipient (131026/131030), closed 24 h window (131047) and invalid requests are recorded, not retried.
- **Token/permission/number problems** (190, 10, 200–299, 133010, 368…) raise one deduplicated `WHATSAPP_UNAVAILABLE`
  review item instead of failing silently.
- **Disconnection** (`account_update` events `PARTNER_REMOVED`, `ACCOUNT_OFFBOARDED`, `ACCOUNT_VIOLATION`,
  `ACCOUNT_RESTRICTION`, `DISABLED_UPDATE` for our WABA) raises a HIGH `WHATSAPP_DISCONNECTED` review item. It
  records the reason and who initiated it, never the phone number. `ACCOUNT_RECONNECTED` and other events are only
  logged.
- **Messages that are too long** get an explanation instead of silence.
- **Tests can no longer use real credentials**: the harness blanks `WHATSAPP_*`/`SMS_*` from `.env` and refuses
  outbound HTTP. Before this change, a populated `.env` leaked into the suite, so a test without its own HTTP mock
  could call the real Graph API.

Known limits (decisions or work outside this change): no message templates, so nothing reaches a customer more than
24 h after their last message (error 131047 is recorded). No opt-out (STOP) handling and no staff hand-over rule.
Voice notes, video, location and contacts get a polite "typed messages only" reply. A reply that fails with a
retryable error and is re-sent can arrive after a later reply.

## 7. Live acceptance checklist

Run only after §3 is complete, on the deployed endpoint, from a phone you control. Record date, result and evidence
(log line or `channel_message`/`whatsapp_inbox` row; never copy message text or numbers into tickets).

| # | Check | How to verify | Result |
|---|---|---|---|
| 1 | The organisation's number is connected to Cloud API (or coexistence) | `whatsapp_account_check.py`: real number, `platform_type=CLOUD_API`, `VERIFIED`, `is_on_biz_app` as chosen | ☐ |
| 2 | Meta can verify and reach the webhook | *Verify and save* succeeds; check script shows callback URL + `messages` field; API log `whatsapp_webhook` | ☐ |
| 3 | An incoming message reaches WEZA | send "I need 5 million for stock for my shop"; `whatsapp_inbox` row → `DONE` | ☐ |
| 4 | It is processed by the existing agent | a `customer_journey` graph instance for that number reaches `CONFIRM_INTENT` | ☐ |
| 5 | The agent uses business logic | the reply summarises amount/purpose/customer type with *Yes/Change* buttons; later, options come from matching | ☐ |
| 6 | The reply is sent from the organisation's number | `channel_message.provider=whatsapp_cloud`, `status=SENT`, wamid set; the chat shows the business name | ☐ |
| 7 | The customer receives it | `provider_status` becomes `delivered` then `read` | ☐ |
| 8 | Follow-ups keep workflow state | tap *Yes*, then continue: same journey advances (`VERIFY_PHONE` …), no new journey | ☐ |
| 9 | Duplicates and failures are safe | Meta's retries leave a single inbox row (unique wamid); `/healthz` shows no growing `oldest_pending_event`; no `WHATSAPP_*` review items | ☐ |
| 10 | Coexistence: the app keeps working | a staff reply from the app is delivered and WEZA does not react to it | ☐ |
| 11 | Coexistence: disconnection is noticed | optional, in a quiet hour: *Disconnect* in the app → a `WHATSAPP_DISCONNECTED` review item appears; reconnect with Embedded Signup and re-run check 1 | ☐ |

## Sources

- Meta, *Onboard WhatsApp Business app users* (coexistence):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/
- Meta, *Webhooks overview* (fields, 200 acknowledgement, retries up to 7 days):
  https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/overview
- Meta, *Graph API versions*: https://developers.facebook.com/docs/graph-api/changelog/versions
