# CRB identity verification (GnuGrid CRB) and the WhatsApp OTP review

Status (2026-10-16): **implemented and tested against a simulated bureau. Not yet exercised against GnuGrid** —
the configured base URL is the LIVE, charged environment and no live call has been made. See §9 before any live test.

## 1. What changed, in one paragraph

After a customer gives their National ID number (NIN), WEZA asks for their date of birth and their consent, sends one
**KYC enquiry** to GnuGrid CRB, and compares the bureau's record with the name and date of birth the customer gave.
The result is stored as an outcome (never the bureau's data) and shown to institutions. The check is **advisory**: it
never blocks a customer, and institutions may require "identity verified" in their product rules. Separately, the
WhatsApp journey no longer sends a verification code into the same chat the customer is writing from.

## 2. State before the change (audit)

1. Customer data came from the journey's question paths (`admin_config.QUESTION_PATHS`): full name, optional NIN,
   then type-specific questions. Facts are provenance-tracked; identity values sit in the encrypted vault.
2. Everything was self-reported. Notably, **typing any well-formed NIN set `verification_level = "IDENTITY"`**, and
   institutions saw that level.
3. Documents: quarantine → malware/type checks → encrypted storage; content not compared with anything.
4. Customer-provided data drives the quality score, product rules (`matching/rules.py`), matching/appetite and the
   routing gate `verification_level != "NONE"`. Credit decisions stay with institutions (BRD §8, TSD §§184–186).
5. WhatsApp messages are tied to the sender's phone (blind index); the customer record is found/created by phone.
6. OTP lived only in the VERIFY_PHONE node (6 digits, hashed, 5-min expiry, 5 attempts, 3 resends, 30 s cool-down,
   per-phone/IP limits). Success linked the customer, set PHONE_VERIFIED and issued a web/app session.
7. Needed: a bureau client and service, enquiry consent, a journey stage, a verification record, a correct
   `verification_level`, an institution-visible status, and an exception in the zero-integration boundary test.

## 3. GnuGrid CRB Enquiries API v1.08 — contract used

| Item | Contract (from the supplied specification) |
|---|---|
| Auth | `POST {CRB_BASE_URL}/v1/oauth/token` — `grant_type=client_credentials`, `client_id`, `client_secret` → `{token_type: "Bearer", expires_in, access_token}`; failure `{error: "invalid_client", ...}` |
| KYC enquiry | `POST {CRB_BASE_URL}/v1/kyc-enquiries/request/new` — `identifier` (NIN), `entity_type: 0` (individual), `identification_type: "ii_country_id"`, `reason` (= `CRB_ENQUIRY_REASON`), `client_consented: "Yes"`, `pi_code` (= `CRB_PI_CODE`, aggregator) |
| Response | `enquiry.{id, reference, status: PENDING/INCOMPLETE/SUCCESSFUL/FAILED, cost, formal/informal {matches, individuals[{individual_id, surname, forename1..3, date_of_birth, ...}]}}` |
| Rules from the spec | "matches … must always be 1 else it is a mismatch"; "All SUCCESSFUL requests are charged" |
| Errors | `{status:"error", message, code}` 400/401/403/404/405/500/503; billing `{subscription: NONE/INSUFFICIENT/EXPIRED/CANCELLED}` |
| Not used | Credit enquiry/report, KYC report, PDF/base64 reports |

## 4. How it works

**Client** — `weza/domains/verification/gnugrid.py` (the only bureau code): token cache (refreshed 60 s early, one
refresh on 401), KYC enquiry, typed results, error classes `OK / AUTH / BILLING / INVALID / INVALID_IDENTIFIER /
UNAVAILABLE / UNCERTAIN / PROTOCOL`. HTTPS only, certificate validation on, 20 s timeout. Because the API has no
idempotency key and charges every SUCCESSFUL enquiry, it retries **only** when the request never left (connection
refused / connect timeout); a timeout after sending is `UNCERTAIN` and is never resubmitted.

**Service** — `weza/domains/verification/service.py`: consent evidence, input checks, idempotency, interpretation,
persistence, customer projection, operations alerts.

- *Idempotency*: key = customer + NIN (blind index) + claimed name tokens + claimed date of birth. A final outcome for
  a key is reused; a key is never enquired while an attempt is in flight (advisory lock + own committed transaction,
  so a crash after the paid call cannot cause a second enquiry — a stale `REQUESTED` attempt becomes `UNCERTAIN`).
  `UNAVAILABLE`/`CONFIG_ERROR` may be retried after 1 hour, at most 3 attempts per key; at most 3 checks per customer
  per day from the journey.
- *Interpretation* (pure function, approved rule): `VERIFIED` only when the bureau status is SUCCESSFUL, exactly one
  consistent individual profile is returned (formal and informal agreeing), the claimed date of birth equals the
  bureau's, and the bureau surname plus at least one bureau forename appear in the claimed full name (case,
  punctuation, accents and order ignored). Otherwise: `DISCREPANCY` (name and/or date of birth differ),
  `NO_RECORD` (no match), `AMBIGUOUS` (more than one match, or formal/informal disagree), `INCONCLUSIVE` (record lacks
  a compared field), `PENDING` (bureau PENDING/INCOMPLETE — the API offers no way to fetch the final result),
  `UNAVAILABLE` (FAILED status, 429, 5xx, unreachable), `UNCERTAIN`, `INVALID_IDENTIFIER`, `CONFIG_ERROR` (auth,
  billing, invalid request, unreadable response).
- *Projection*: only `VERIFIED` sets `verification_level = "IDENTITY"`, fact `identity.crb_verified = true`
  (state VERIFIED) and marks the name/NIN/date-of-birth facts VERIFIED. Changing any of those details later voids it.
- *Alerts*: `CRB_UNAVAILABLE` (HIGH, deduplicated) for configuration/credential/subscription problems;
  `CRB_CHECK_UNRESOLVED` for UNCERTAIN/PENDING; `IDENTITY_UNVERIFIED` (MEDIUM, worded "not an indication of fraud")
  when a customer's correction still doesn't verify.

**Journey** — node `VERIFY_IDENTITY` in `need/journey.py`, entered from BUILD_PROFILE when the bureau is configured,
a NIN was given and no final result exists for the current details:

```
NIN given ─▶ date of birth? (skip → continue, no check)
          ─▶ consent text + [Yes, check] [No, skip]   (No → continue, no check)
          ─▶ one KYC enquiry ─▶ outcome (code, not AI) ─▶
     VERIFIED ............ "match the record" → next question
     DISCREPANCY ......... which field differs (name / date of birth), never the bureau's values
                           → [Fix my name] [Fix my date of birth] [Continue]; one correction, re-check needs a new "Yes"
     NO_RECORD / bad ID .. → [Check my ID number] [Continue]
     still unverified after the correction → continue + IDENTITY_UNVERIFIED review
     UNAVAILABLE / CONFIG_ERROR → "isn't available right now" → continue
     AMBIGUOUS / INCONCLUSIVE / PENDING / UNCERTAIN → "couldn't confirm automatically" → continue
```
Web, app and WhatsApp run the same graph, so the requirements are identical on every channel. The AI never sees
bureau data and never produces verification messages.

**Institutions** — the opportunity view's `verification` block adds `identity_check` (outcome), `source`,
`checked_at` and per-field MATCH/MISMATCH; product rules can use `identity_verified` (rule builder updated).

**Data kept** — `identity.verification_check` (migration `0005`): outcome, per-field results, bureau enquiry
id/reference/status/cost, match counts, error class, consent version/text hash/channel/time. Never the NIN, names,
date of birth, photo or the bureau response. The date of birth itself is stored encrypted in the identity vault.

## 5. WhatsApp OTP decision

On WhatsApp the code was sent **into the same chat the customer was writing from**; Meta had already authenticated
the sender (signed webhook), and the web session it created was never used on WhatsApp. So it proved nothing new.
- **Removed** from the WhatsApp journey: the chat number is recorded as phone-verified by the channel
  (audit `customer.phone_verified`, `method: "whatsapp_channel"`).
- **Kept** for web and app (a browser proves nothing about a phone, and the OTP issues their session), with all
  limits unchanged. The OTP service, templates and `SMS_PROVIDER=whatsapp` delivery remain for those journeys.
- FSD-IDV-001's outcome ("Set Phone Verified") is unchanged; its WhatsApp step should be updated in the FSD.
- Neither channel proves legal identity — that is what the bureau check addresses.

## 6. Configuration

`CRB_BASE_URL` (https, without `/v1`), `CRB_CLIENT_ID`, `CRB_CLIENT_SECRET`, `CRB_ENQUIRY_REASON`, `CRB_PI_CODE`
(optional) — enter them with `python scripts/configure_env.py` (hidden input for the secret). Unset = the identity
step is skipped. `scripts/crb_connection_check.py` checks the credentials **without** an enquiry.

## 7. Tests

`tests/test_crb_client.py` (request contract, token reuse/refresh, every failure class, retry rules, no PII in logs,
interpretation rules) and `tests/test_identity_verification.py` (WhatsApp and web journeys: consent, decline, skip,
not configured, discrepancy + correction, escalation, no record, outage, timeout, bad credentials, duplicate webhook,
idempotency, crash recovery, voiding on new details, rule field). All bureau calls are faked; tests blank any real
`CRB_*` values from `.env` and block network access.

## 8. Decisions taken (2026-10-16)

LIVE environment (no live calls without explicit approval) · advisory check · surname + one forename + exact date of
birth · Weza enquires as an aggregator (`pi_code`).

## 9. Live verification plan (needs your approval at each step)

1. Fill `CRB_*` (configure_env). Run `scripts/crb_connection_check.py`: token only, no enquiry, no charge.
2. **One** controlled KYC enquiry with the NIN, name and date of birth of a consenting volunteer (ideally staff),
   through a WhatsApp journey: charged once if SUCCESSFUL. Expected: VERIFIED, one `verification_check` row.
3. Optional: the same volunteer with a deliberately wrong date of birth (a second charged enquiry) → DISCREPANCY.
4. Check `cost`, `bureau_status` and the GnuGrid float/billing page after each call.

## 10. Open questions

1. **`pi_code`** to send (one code for WEZA's own checks, or per institution?) and the exact **`reason`** wording.
2. **Consent text** (`CONSENT_VERSION 2026.1-draft` in `verification/service.py`) needs legal approval.
3. **Retention** period for `verification_check` rows (no automatic deletion exists yet).
4. GnuGrid: meaning of PENDING/INCOMPLETE and how to obtain the final result; whether a no-match enquiry is charged;
   rate limits; token lifetime; whether 404 can mean "no such customer".
5. Whether existing customers whose NIN was previously treated as "IDENTITY" should be re-checked (their level is
   now only raised by a VERIFIED check; existing rows were not changed).
