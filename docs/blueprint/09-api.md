# 09 — API / Service Map

Base: `/api/v1`. JSON. OpenAPI generated at `/api/v1/openapi.json` and served at `/docs` (non-prod).

**Common error contract (TSD §59)**
```json
{ "error": { "code": "CONSENT_REQUIRED", "message": "Consent is required before sharing.", "correlation_id": "…", "retryable": false, "details": [{"field": "…", "issue": "…"}] } }
```
**Idempotency (TSD §60):** `Idempotency-Key` header is required on starred (★) endpoints. The same key + same body returns the stored response; the same key + a different body returns 422 `IDEMPOTENCY_KEY_REUSED`.
**Auth:** customer = session bearer token (from OTP) or anonymous journey token before verification; institution/admin = access token (15 min) + refresh token in an httpOnly cookie, MFA step-up claim. **Tenant context comes only from the token** (TSD §47).

## Channel & customer
| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/channels/whatsapp/webhook` | Meta webhook (signature-verified) → canonical message | HMAC |
| GET | `/channels/whatsapp/webhook` | Meta verify challenge | token |
| POST | `/channels/simulator/messages` | Simulator → same gateway | flag |
| POST | `/journeys` | Start journey (attribution) → journey token | public, rate-limited |
| POST | `/journeys/{id}/messages` | Customer message → next step | journey token |
| GET | `/journeys/{id}` | Current node, understanding card, next question, quick replies | journey token |
| POST | `/journeys/{id}/intent/confirm` | Confirm/correct intent | journey token |
| POST | `/auth/otp/request` | Issue OTP | public, rate-limited |
| POST | `/auth/otp/verify` | Verify → customer session | public, rate-limited |
| GET/PATCH | `/me/profile` | Facts with provenance / correct | customer |
| POST | `/me/documents` | Upload (multipart) → pipeline | customer |
| GET | `/me/needs`, `/me/needs/{id}` | Needs, readiness, status | customer |
| GET | `/me/needs/{id}/matches` | Ranked matches + explanation | customer |
| PUT | `/me/preferences` | Preferences | customer |
| POST | `/me/matches/{id}/select` | Select | customer |
| GET | `/consent-templates/current?purpose=` | Text + version | customer |
| POST ★ | `/me/matches/{id}/consent` | Grant consent → saga | customer |
| POST | `/me/consents/{id}/withdraw` | Withdraw | customer |
| POST | `/me/needs/{id}/waiting-room` | Opt in / reconfirm | customer |
| POST | `/me/opportunities/{id}/withdraw` | Withdraw opportunity | customer |
| POST | `/me/opportunities/{id}/rescue` | Want alternatives yes/no | customer |

## Institution
| Method | Path | Permission |
|---|---|---|
| POST | `/institutions/applications` | public |
| POST | `/auth/login`, `/auth/mfa/verify`, `/auth/refresh`, `/auth/logout`, `/auth/mfa/enrol` | — |
| GET | `/inst/onboarding` | any member |
| POST | `/inst/activate` | `institution.activate` |
| GET/POST/PATCH | `/inst/users` | `users.manage` |
| GET/POST/PUT | `/inst/products`, `/inst/products/{id}/versions` | `product.read/create` |
| POST | `/inst/products/{id}/submit`, `/approve`, `/reject`, `/pause`, `/resume`, `/archive` | `product.create` / `product.approve` |
| POST | `/inst/products/extract` | `product.create` |
| GET/POST/PUT | `/inst/appetites`, versions | `appetite.read/edit` |
| POST | `/inst/appetites/{id}/simulate` | `appetite.simulate` |
| POST | `/inst/appetites/{id}/approve`, `/activate`, `/pause`, `/resume` | `appetite.activate` |
| PUT | `/inst/appetites/{id}/capacity` | `appetite.edit` |
| GET/PUT | `/inst/routing`, `/inst/service-targets`, `/inst/notification-prefs` | `routing.manage` / self |
| POST | `/inst/sandbox/runs` | `sandbox.run` |
| GET | `/inst/command-centre` | role-shaped |
| GET | `/inst/my-day` | `opportunity.read` (own) |
| GET | `/inst/opportunities?filters` | `opportunity.read` |
| GET | `/inst/opportunities/{id}` | `opportunity.read` + PDP/consent |
| POST | `/inst/opportunities/{id}/assign` | `opportunity.assign` |
| POST ★ | `/inst/opportunities/{id}/status` | `opportunity.update_status` |
| POST ★ | `/inst/opportunities/{id}/outcome` | `opportunity.update_status` |
| GET | `/inst/opportunities/{id}/documents/{docId}` | short-lived signed stream |
| GET/POST | `/inst/previews`, `/inst/previews/{id}/interest` | `preview.read/interest` |
| GET | `/inst/team` | `team.manage` |
| GET | `/inst/intelligence/radius`, `/demand`, `/product-gaps`, `/insights` | `analytics.*` |
| POST | `/inst/insights/{id}/dismiss` | `appetite.edit` |
| POST | `/inst/ask` | any member (tools PDP-checked) |
| GET | `/inst/reports/*`, `/inst/reports/export` | `analytics.read` |
| GET | `/inst/billing`, `/inst/billing/events` ; POST ★ `/inst/billing/events/{id}/dispute` | `billing.view` / `billing.dispute` |
| GET | `/inst/audit/consents`, `/inst/audit/access` | `consent.audit` |
| GET/PATCH | `/inst/notifications`, `/{id}/ack` | self |

## Admin (`/admin/*`, WEZA users with MFA)
institutions (list, review, verify/reject, pause/suspend/resume), products & appetites (pause), market-state, health, opportunities monitor, customers (vault lookup with reason), review-queue (list/resolve), integrity cases, disputes (decide), commercial (contracts CRUD, events, unit economics), graph inspector (`/admin/graph/{type}/{id}`), audit, consents, notifications/dead-letters (replay), config (country, consent templates publish, question paths, weights, flags, kill switches, AI mode).

## Internal service map (module → public functions)
`identity.service`: issue_otp, verify_otp, vault_put, vault_get(reason, actor) · `need.service`: start_journey, handle_message, confirm_intent · `customer.service`: upsert_fact, snapshot_profile, readiness · `matching.service`: match_need, clear_market(trigger), simulate(criteria) · `consent.service`: grant, withdraw, is_valid(scope) · `opportunity.service`: qualify_saga, transition, assign, report_outcome · `trust.pdp`: decide(actor, action, resource, purpose) · `trust.disclosure`: view_opportunity(actor, opp_id) · `notification.service`: dispatch(event) · `commercial.service`: on_routed, open_dispute, decide · `integrity.service`: evaluate(event) · `intelligence.*`: AI capabilities, radius, gaps, insights, briefings.
