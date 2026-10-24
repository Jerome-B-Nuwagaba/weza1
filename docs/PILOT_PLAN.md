# WEZA closed pilot plan

A closed pilot with two or three real institutions and a limited set of invited customers, run before general launch. It
tests the V1 flows in BRD §41–42 with real people and measures the KPIs in BRD §43. It starts only after
[GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) is complete. Dates are left for you to set.

## Scope

- **Institutions:** two or three, of different kinds (for example a bank, a SACCO, a fintech lender). Each configures one or
  two products and a mandate, routes to a small team, and works the opportunities through its own process.
- **Customers:** invited individuals and small businesses, reached by WhatsApp and the web chat. Start at 20–30 and grow
  only while the checks below hold.
- **Not in the pilot:** exclusive routing (needs the BRD §29 terms decided), push notifications, per-institution Microsoft
  tenants, and any billing that charges real money.

## Phases

| Phase | Length | What happens | Move on when |
|---|---|---|---|
| 0. Rehearsal | 1 week | Staff walk every flow on UAT with test phones: customer journey, institution onboarding, alerts, briefs | No open defect that blocks a flow; restore rehearsal done |
| 1. Institutions first | 1–2 weeks | Onboard each institution (verification, users, products, mandate, routing, notification channels) and activate | Every institution shows all seven activation readiness items green |
| 2. Seeded demand | 1 week | Staff and friendly customers create real requests so each mandate has something to match | Each mandate has received at least one qualified opportunity |
| 3. Invited customers | 2–4 weeks | Invited customers use WhatsApp and web; institutions contact them and report outcomes | KPIs hold for two weeks in a row |
| 4. Review | 1 week | Review KPIs, disputes, complaints and feedback; decide on opening up | Written go or no-go decision |

## What to measure (BRD §43)

| Area | Measure | Where it comes from |
|---|---|---|
| Customer | Profile completion, consent rate, institution selection, abandonment | Customer funnel in Admin |
| Matching | Match rate, no-match rate, near-match demand, matches per customer | Command Centre and Admin |
| Institution | Qualified opportunities, contact rate, response time, reported progression and outcomes | Institution reports and weekly brief |
| Quality | Duplicate rate, stale opportunity rate, complaints, response SLA, disputes | Admin integrity and commercial views |
| Marketplace | Active customers, requested financing, active products and mandates | Admin overview |

Approvals and disbursements are always reported by the institution; WEZA records them and never decides credit.

## Safety limits during the pilot

- Keep `RETENTION_ENABLED` off until retention is signed off; keep `AI_DOCUMENT_EXTRACTION` off unless privacy has approved.
- Review the Admin review queue and integrity cases daily in the first two weeks.
- Use the kill switches (pause routing, billing events, a channel, AI) if anything misbehaves, then investigate.
- Every complaint gets a named owner and an answer within one working day.
- Customers are told they are in a pilot and how to withdraw consent; withdrawals are honoured immediately.

## Roles

| Role | Responsibility |
|---|---|
| Pilot lead (WEZA) | Owns the schedule, the KPI review and the go or no-go recommendation |
| Support (WEZA) | Answers customers and institutions; logs every issue |
| Institution champion | One named person per institution who works the queue and reports outcomes |
| Data protection lead | Signs off retention and AI document reading, and handles any suspected exposure |

## Exit criteria for opening up

- KPIs stable for two consecutive weeks with no unexplained drop in consent rate or contact rate
- No open data-protection incident and no unresolved dispute older than 14 days
- Every pilot institution says in writing it would continue
- All outside items in the go-live checklist closed, or consciously deferred with an owner
