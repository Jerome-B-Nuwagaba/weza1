# WhatsApp channel runbook

How WhatsApp works in WEZA, how to run it locally against the simulator, and how to connect a real Meta test number.
Real values live ONLY in `services/core-api/.env` (untracked). Anything that is empty, unset or `REPLACE_ME` means
"not configured": the app stays in simulator mode and never calls Meta or an SMS provider.

## How customers use WEZA
The conversation happens only on WhatsApp. Anyone can message the organisation's WhatsApp number directly, describe the financing
they need and be answered — no website needed. The website only hands people over: the landing page's *Continue on WhatsApp*
button and `/start` (used by QR codes and campaign/partner links, e.g. `/start?src=qr&cmp=Q4SME&q=...`) open
`wa.me/<WHATSAPP_BUSINESS_NUMBER>` with the need and the campaign reference pre-filled, as if texting a person. The institution
side (sign-in, workspace, opportunity feed) stays on the web. Outcome updates reach the customer inside WhatsApp (no web links).
Note: Meta only allows free-form business messages within 24 hours of the customer's last message; later updates need approved
templates (not yet built).

## Flow
Meta → `POST /api/v1/channels/whatsapp/webhook` (signature checked, message stored once in `notification.whatsapp_inbox`,
200 returned) → outbox event → worker → `public.inbound()` → `need.service.handle_input()` → replies through
`notification.send_customer_message()` (Cloud API when configured, otherwise the simulator inbox).
Delivery receipts (`statuses`) update `notification.channel_message` only; they never advance a journey.
The simulator (`/whatsapp-sim`) calls `public.inbound()` directly and synchronously.

## Settings (names only)
`WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_API_VERSION`,
`WHATSAPP_BUSINESS_NUMBER`, `WHATSAPP_BUSINESS_ACCOUNT_ID` (templates only), `SMS_PROVIDER`, `SMS_API_KEY`, `SMS_USERNAME`,
`SMS_SENDER_ID`. Fill them with `python scripts/configure_env.py` (hidden input, writes only `.env`).

>>> USER INPUT REQUIRED: the real values above (Meta developer dashboard → your app → WhatsApp → API Setup / Configuration;
App settings → Basic for the app secret) and your SMS provider's name and credentials.

## Local replay (fake secrets, simulator mode)
Set the same fake values in the API terminal, restart, then replay payloads:

    set WHATSAPP_APP_SECRET=FAKE_local_app_secret_not_real
    set WHATSAPP_VERIFY_TOKEN=FAKE_local_verify_token_not_real
    .venv\Scripts\python scripts\dev_api.py
    .venv\Scripts\python scripts\replay_whatsapp_webhook.py list

## Real (non-demo) environment: from sign-up to first opportunity
1. **First WEZA administrator** (once): `python -m weza.bootstrap` asks for an email and a hidden password, or set
   `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` (the container start script runs it). Demo data is never created
   when `SEED_DEMO=false`. Sign in at `/login`.
2. **Institution joins**: `/for-institutions` → *Join WEZA* → application → the institution administrator can sign in at once.
3. **WEZA verifies**: sign in as the WEZA administrator → *Institutions* → open the application → *Approve* (reason required).
4. **Institution configures** (Activation page lists who can do each step; maker-checker applies): add users (a manager/admin,
   an officer, a Business/Product or Credit/Risk lead, and a second approver) → product (draft, submit, a *different* person
   approves) → appetite (draft, run simulation, a different person approves) → routing → notification preferences → **ACTIVATE**.
5. **Customers arrive** from the website's *Continue on WhatsApp* link (it carries the need and the campaign/QR reference)
   or by messaging the business number. They verify by OTP, answer the profile questions, send documents in the chat,
   choose an institution and consent. The opportunity then appears in that institution's *Opportunity Feed*, assigned by
   its routing rules; the officer sees the consented identity, the manager can reassign, and outcomes are reported back.
An institution with no matching product or appetite simply receives nothing: customers whose request fits nobody are offered
the Waiting Room.

## Photos and documents
After the phone is verified, a customer can send photos (JPG/PNG) and PDFs in the chat (up to 10 MB). WEZA downloads the file
from Meta with `WHATSAPP_TOKEN`, runs the normal document pipeline (quarantine → scan → type check → encrypted storage) and
replies "Got it". The document type comes from the caption/filename ("my payslip", "bank statement.pdf") or else the first
document still outstanding. A journey waiting for a missing document resumes automatically. Before verification, or with no
open request, the customer gets a short instruction instead. Voice notes, video, stickers, locations and contacts get the
"typed messages" reply. Sending a photo as a *document* in WhatsApp keeps its full quality.

## Verification codes (OTP) through Meta
Set `SMS_PROVIDER=whatsapp` and the codes are sent through the WhatsApp Cloud API with the same `WHATSAPP_*` credentials.
Meta only delivers free-form messages inside 24 h of the customer's last message, so for journeys started on the web/app
create an Authentication template in WhatsApp Manager (copy-code button), wait for approval and set
`WHATSAPP_OTP_TEMPLATE_NAME` (+ `WHATSAPP_OTP_TEMPLATE_LANGUAGE`). Without it only WhatsApp-started journeys work and a web
OTP fails with Meta error 131047. Dev mode (`OTP_DELIVERY=display`) still shows the code in the UI. The template payload shape is
UNVERIFIED AGAINST REAL META.

## Real end-to-end test with Meta
1. Fill `.env` (configure_env.py), restart the API; the startup log line `channel_config` should list the names as configured.
2. Expose the local API: `ngrok http 8000` (or `cloudflared tunnel --url http://localhost:8000`).
3. Meta dashboard → WhatsApp → Configuration → Webhook: callback URL `https://<tunnel>/api/v1/channels/whatsapp/webhook`,
   verify token = your `WHATSAPP_VERIFY_TOKEN`; click Verify, then subscribe to the `messages` field.
4. API Setup → "To" field: add and verify your own phone as a test recipient (test numbers can only message verified recipients).
5. Message the test business number from that phone. Expected: a reply within a few seconds; `channel_message` rows
   gain `provider_status` sent → delivered → read. Send an image or voice note: you get the "typed messages" reply.
6. Outside the 24-hour customer-service window Meta rejects free-form messages (needs templates — not implemented).

## Not implemented (decisions needed from your team)
- **Templates**: required to message customers first or after 24 h of silence (WEZA reminders, waiting-room notices). Needs
  approved template names/languages, a WABA id, and a send path that maps events → templates.
- **Opt-in policy**: how/when customers consent to WhatsApp messages, how opt-out ("STOP") is honoured, and where it is recorded.
- **Other SMS gateway** (only if you ever want a non-Meta fallback): slot in `weza/domains/notification/sms.py`.
