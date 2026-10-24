# WEZA go-live checklist

Production refuses to start while `Settings.production_problems()` (`services/core-api/weza/config.py`) lists anything. That
covers what can be checked from configuration. This checklist adds what cannot: decisions, sign-offs and outside accounts.
Tick every item, with a name and a date, before real customers are invited.

## 1. Enforced by the application at startup (set these, then start the API)

| Setting | Required value |
|---|---|
| `ENV` | `production` |
| `SECRET_KEY`, `VAULT_MASTER_KEY`, `BLIND_INDEX_KEY` | Generated, not the development defaults; kept in the host's secret store |
| `MFA_ENFORCED` | `true` |
| `LOGIN_IP_LIMIT` | 100 or less (the CI container raises it; production must not) |
| `OTP_DELIVERY`, `SMS_PROVIDER` | `sms`, and a provider that delivers (Africa's Talking live account, Twilio, Infobip, or WhatsApp) |
| `IDENTITY_PROVIDER`, `GNGRID_USE_MOCK` | `gnugrid`, `false`, with every CRB credential present |
| `MALWARE_SCANNER` | `clamav` with `CLAMAV_HOST` reachable |
| `SMTP_URL` | Set (staff email alerts) |
| `CORS_ORIGINS` | The exact web origins, never `*` |

## 2. Set in production but not enforced

| Setting | Why |
|---|---|
| `RETENTION_ENABLED` | Leave `false` until the retention policy (`retention:UG` in country config) has legal sign-off, then turn on. Run the dry run in Admin first. |
| `AI_DOCUMENT_EXTRACTION` | `false` until privacy has approved sending ID photos and licences to the AI provider. Customers then type their details. |
| `METRICS_TOKEN` | Set, and give it only to the monitoring system. Without it `/metrics` is closed. |
| `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_CLIENT_SECRET`, `ENTRA_REDIRECT_URI` | Needed for Microsoft sign-in. The tenant must be a single tenant GUID; multi-tenant values are refused. |
| `PUBLIC_WEB_URL` | The real web address, used in links inside alerts, briefs and Teams cards |
| WhatsApp variables | See [WHATSAPP_GO_LIVE.md](WHATSAPP_GO_LIVE.md) |

## 3. Outside accounts and sign-offs (cannot be built from here)

- [ ] gnuGRID: production credentials, per-enquiry billing agreed, and the business-verification specification received
- [ ] SMS provider: live keys and an approved sender ID
- [ ] Meta WhatsApp: business verification, number connected, templates approved
- [ ] Privacy: sign-off on ID photos going to the AI provider, and on the retention schedule
- [ ] Legal: terms for exclusive routing (BRD §29) decided, or the feature stays off
- [ ] Regulator: telecom and NIRA registration checks complete
- [ ] Hosting: production database, backups and a restore rehearsal (see [OPERATIONS.md](OPERATIONS.md))
- [ ] Microsoft Entra app registered, and the redirect URI added

## 4. Verify on the production candidate

- [ ] CI green on the commit being deployed (lint, security, tests, image, web, browser, secret scan)
- [ ] `alembic heads` shows exactly one head and the migration ran on a copy of production data
- [ ] `/healthz` is green and `/metrics` answers only with the token
- [ ] A real customer journey end to end from a test phone: ID photo, OTP, options, consent, credit check, hand-off
- [ ] A staff sign-in with MFA, and with Microsoft if enabled
- [ ] A Teams test message, an SMS alert, and a daily brief received by a test user
- [ ] Admin retention dry run reviewed; step-up and reason required for the real run
- [ ] An administrator can use the kill switches: pause routing, pause billing events, disable a channel, set AI mode

## 5. Roll-back

Keep the previous image tag. Migrations are forward-only and additive; if a release must be reverted, redeploy the previous
image against the migrated database (the previous release ignores new columns). Never restore a backup over live data
without the incident lead's approval.
