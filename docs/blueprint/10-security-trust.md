# 10 — Security & Trust Model

## 1. Layers (TSD §68)
Edge (HTTPS only, HSTS, security headers, CORS allow-list) → rate limiting (OTP, login, journeys, uploads, AI, simulation; keyed by IP, phone hash, user, tenant) → authentication → **tenant resolution from token only** → RBAC permission check → **Policy Decision Point** for sensitive resources → **Data Disclosure Gateway** for identifiable fields → repository with mandatory tenant filter (+ Postgres RLS in production) → audit.

## 2. Role / permission matrix (FSD §3, §17; TSD §48)

Legend: ● full · ◐ own/team scope · ○ read-only · – none

| Permission | Inst Admin | Executive | Business/Product | Credit/Risk | Manager | Officer | Compliance | WEZA Ops | WEZA Commercial | WEZA Super |
|---|---|---|---|---|---|---|---|---|---|---|
| users.manage | ● | – | – | – | – | – | – | ○ | – | ● |
| institution.activate | ● | – | – | – | – | – | – | – | – | – |
| product.read | ● | ○ | ● | ● | ○ | ○ | ○ | ○ | – | ○ |
| product.create | ○ | – | ● | ◐ | – | – | – | – | – | – |
| product.approve (≠ author) | ● | ● | ● | ● | – | – | – | – | – | – |
| appetite.edit / simulate | ○ | ◐ sim | ● | ● | – | – | – | – | – | – |
| appetite.activate (≠ author) | ● | ● | – | ● | – | – | – | – | – | – |
| routing.manage | ● | – | – | – | ● | – | – | – | – | – |
| sandbox.run | ● | – | ● | ● | – | – | – | – | – | – |
| opportunity.read (identifiable) | ○ | – | – | – | ◐ team | ◐ assigned | ◐ audit | ○ w/ reason | – | ○ w/ reason |
| opportunity.read (aggregate/feed meta) | ● | ● | ● | ● | ● | ◐ | ● | ● | – | ● |
| opportunity.assign | ● | – | – | – | ● | – | – | – | – | – |
| opportunity.update_status | – | – | – | – | ● | ◐ assigned | – | – | – | – |
| preview.read / interest | – | ○ | ● | ● | ● | – | – | – | – | – |
| analytics.read / executive | ● | ● | ● | ● | ◐ | ◐ | ○ | ● | ● | ● |
| billing.view / dispute | ● | ● | – | – | – | – | – | ○ | ● | ● |
| consent.audit | ○ | – | – | – | – | – | ● | ● | – | ● |
| admin.verify_institution | – | – | – | – | – | – | – | ● | – | ● |
| admin.kill_switch / config | – | – | – | – | – | – | – | ◐ pause | – | ● |
| admin.dispute_decide | – | – | – | – | – | – | – | – | ● | ● |
| admin.vault_lookup | – | – | – | – | – | – | – | ● reason | – | ● reason |

## 3. Policy Decision Point (TSD §28)
`decide(actor, tenant, role, action, resource, opportunity_relationship, consent_state, purpose, data_class, policy_version) → PERMIT | DENY | PERMIT_WITH_RESTRICTED_FIELDS(fields)`. Policies are code (versioned module `policies_v1.py`) with a table-driven field map: data category → fields. Every DENY and every identifiable PERMIT is logged.

## 4. Data Disclosure Gateway (TSD §29)
Authentication → Tenant (opportunity.institution_id == actor tenant) → Role/Policy → Opportunity access (assigned officer / team manager / admin / compliance) → Consent (GRANTED, not withdrawn, institution matches, purpose = `INSTITUTION_CONTACT_FOR_FINANCING`) → Data scope (consented categories) → returns **only authorised fields**, pulled from the Identity Vault at read time. Previews use a separate allow-list serializer (Level 2). Aggregates use k ≥ 5 suppression (Level 1).

| Level | Fields |
|---|---|
| L1 Market intelligence | counts, sums, bands; cells < 5 suppressed |
| L2 Preview | segment, sector, region, amount band, business-age band, match band, readiness |
| L3 Qualified (by category) | Contact: name, phone, email, contact window · Identity: NIN, ID doc refs · Business/Employment: business name, registration, employer · Financial: turnover/income, obligations · Documents: authorised docs |

## 5. Identity Vault (TSD §12)
Direct identifiers live only in `identity.vault_record`, encrypted with AES-256-GCM (envelope: data key per record wrapped by a master key from `SecretStore`). Lookup uses an HMAC-SHA256 blind index (phone/NIN). Other domains hold `vault_token` only. Identifiers are never primary keys and never appear in events or logs.

## 6. Authentication
- Customers: phone OTP (6 digits, HMAC-hashed with per-challenge salt, 5 min, 5 attempts, resend 3/15 min, 30 s cooldown, IP/phone throttles), session token 30 days sliding, revocable.
- Institution/WEZA users: argon2id passwords (min 12 chars, breached-pattern check list), TOTP MFA (required for inst. admins + all WEZA users; others per institution policy), lockout 5/15 min, access JWT 15 min (HS256 with a platform-held secret; EdDSA with Key Vault keys planned for production), refresh rotation with reuse detection, step-up MFA for kill switches and vault lookup. Entra ID OIDC adapter planned (C5).

## 7. Data classification (TSD §49)
Each field is classified in `trust/classification.py` (PUBLIC, INTERNAL, CONFIDENTIAL, PERSONAL, HIGHLY_SENSITIVE). The classification drives log redaction, disclosure categories, export restrictions and retention.

## 8. Documents (TSD §42, §51)
Upload → quarantine (not readable by anyone) → scan (adapter) → validation (magic bytes, size ≤ 10 MB, PDF/JPEG/PNG) → encrypted store (object key namespaced `cust/{customer_id}/…`) → classify → optional AI extraction (scanned text only) → customer confirmation → authorised use. Institution access is only through a streaming endpoint behind the Disclosure Gateway, with a 5-minute signed token. There are no public URLs.

## 9. Threats addressed (STRIDE summary)
Spoofing (OTP, MFA, webhook HMAC) · Tampering (append-only audit with DB trigger, hash of consent text, versioned rules) · Repudiation (audit + decision ledger) · Information disclosure (PDP, gateway, vault, redaction, tenant filter + RLS, k-anonymity) · DoS (rate limits, body size limits, AI budgets) · Elevation (server-side permission checks, maker-checker, no client-supplied tenant). Prompt injection: untrusted content delimited, no AI write tools, schema validation. CI runs `pip-audit`, `npm audit`, `bandit`, `gitleaks` and a custom tenant-isolation test suite.

## 10. Kill switches (TSD §75)
Pause All Routing · Suspend Institution · Pause Product · Pause Mandate · Disable channel (web/whatsapp/sms) · AI mode · Pause billing-event creation. Each is audited with actor + reason and requires step-up MFA. Routing-affecting switches trigger G4 re-clearing so customers are not left with dead options.
