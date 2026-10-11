# WEZA V1 — Product, Graph & Loop Architecture Blueprint

**Status:** APPROVED by the Product Owner (8 Oct 2026) — implemented in this repository; see [TESTING.md](../TESTING.md)
**Version:** 0.1 · 8 October 2026
**Sources of truth:** WEZA BRD v1.0 (WHY) · WEZA FSD v1.0 (WHAT) · WEZA TSD v1.0 (HOW) · WEZA Master Product Design, Graph & Loop Engineering Skill

> **Customer:** Tell WEZA what financing you need. **Institution:** Tell WEZA what customers you want.
> **WEZA:** Understand. Qualify. Match. Route. Track. Learn.

This blueprint translates the three authoritative documents into an implementable V1 design. It does not add requirements. Where the documents leave a decision open, the decision is labelled **[Design Recommendation]** with its reasoning. Where documents conflict, the conflict is listed in §3 below with a proposed resolution.

---

## 1. Document map (Skill §68 deliverables)

| # | Deliverable | Location |
|---|---|---|
| 1 | Product architecture summary | [01-architecture.md](01-architecture.md) §1–§6 |
| 2 | Information architecture | [02-experience.md](02-experience.md) §1 |
| 3 | Complete sitemap | [02-experience.md](02-experience.md) §2 |
| 4 | Customer journey map | [03-journeys.md](03-journeys.md) §1 |
| 5 | Institution journey map | [03-journeys.md](03-journeys.md) §2 |
| 6 | Admin journey map | [03-journeys.md](03-journeys.md) §3 |
| 7 | Complete domain graph | [04-domain.md](04-domain.md) §1 |
| 8 | Customer journey graph | [05-graphs.md](05-graphs.md) G1 |
| 9 | Institution onboarding graph | [05-graphs.md](05-graphs.md) G2 |
| 10 | Opportunity lifecycle graph | [05-graphs.md](05-graphs.md) G3 |
| 11 | Market Clearing graph | [05-graphs.md](05-graphs.md) G4 |
| 12 | Customer Waiting Room graph | [05-graphs.md](05-graphs.md) G5 |
| 13 | Institution Capital Deployment graph | [05-graphs.md](05-graphs.md) G6 |
| 14 | Opportunity Rescue graph | [05-graphs.md](05-graphs.md) G7 |
| 15 | Outcome Learning loop | [06-loops.md](06-loops.md) L1 |
| 16 | Product Intelligence loop | [06-loops.md](06-loops.md) L2 |
| 17 | Commercial / Billing loop | [06-loops.md](06-loops.md) L3 |
| 18 | Marketplace Integrity loop | [06-loops.md](06-loops.md) L4 |
| 19 | Notification / Escalation loop | [06-loops.md](06-loops.md) L5 |
| 20 | Human-in-the-loop map | [07-ai-and-agents.md](07-ai-and-agents.md) §5 |
| 21 | Agent / tool graph | [07-ai-and-agents.md](07-ai-and-agents.md) §3–§4 |
| 22 | Graph persistence model | [08-runtime-events.md](08-runtime-events.md) §1 |
| 23 | Graph event model | [08-runtime-events.md](08-runtime-events.md) §2 |
| 24 | Loop stop / retry / failure model | [06-loops.md](06-loops.md) §7 |
| 25 | Screen inventory | [02-experience.md](02-experience.md) §3 |
| 26 | Screen-by-screen functional specification | [02-experience.md](02-experience.md) §4 |
| 27 | Role / permission matrix | [10-security-trust.md](10-security-trust.md) §2 |
| 28 | Core data / entity model | [04-domain.md](04-domain.md) §2 |
| 29 | State-machine map | [04-domain.md](04-domain.md) §3 |
| 30 | Component / design system | [02-experience.md](02-experience.md) §5 |
| 31 | Desktop wireframes | [02-experience.md](02-experience.md) §6 |
| 32 | Mobile / customer wireframes | [02-experience.md](02-experience.md) §7 |
| 33 | High-fidelity UI direction | [02-experience.md](02-experience.md) §5.1 |
| 34 | API / service map | [09-api.md](09-api.md) |
| 35 | Event architecture | [08-runtime-events.md](08-runtime-events.md) §3–§5 |
| 36 | Security / trust model | [10-security-trust.md](10-security-trust.md) |
| 37 | Requirements traceability matrix | [11-traceability.md](11-traceability.md) |
| 38 | Prioritised implementation backlog | [12-backlog-and-qa.md](12-backlog-and-qa.md) §1 |
| 39 | Acceptance-test plan | [12-backlog-and-qa.md](12-backlog-and-qa.md) §2 |
| 40 | Graph observability requirements | [08-runtime-events.md](08-runtime-events.md) §6 |
| + | Deployment, environments, hosting | [13-deployment.md](13-deployment.md) |

---

## 2. Key decisions at a glance

| Area | Decision | Basis |
|---|---|---|
| Shape | **Modular monolith + transactional outbox + background worker** | TSD §4, §55, §82; Skill §66 |
| Backend | **Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic v2** | TSD §4 (FastAPI permitted; one language keeps V1 lean) |
| Database | **PostgreSQL 16** — system of record, separate schemas per domain | TSD §50 |
| Events | **Postgres outbox → worker dispatcher** (Service Bus adapter interface ready) | TSD §54–§57 **[Design Recommendation]** |
| Web | **Next.js 15 (App Router) + TypeScript** — one app, three route groups: `/(customer)`, `/institution`, `/admin` | TSD §4, §82 |
| Mobile | **Flutter 3** customer app (same `/api/v1`) | TSD §4 "React Native *or equivalent*"; Product Owner request |
| AI | **AI Control Plane** with provider adapter (Anthropic Claude) + deterministic fallback; works with no API key | TSD §8, §76, §77 |
| Graphs | **In-house persisted graph runtime** (table-driven nodes/edges, interrupts, timeouts) — not LangGraph | Skill §48, §66 **[Design Recommendation]** |
| WhatsApp | Channel gateway + canonical message contract; **WhatsApp simulator** in web until Meta credentials are supplied | TSD §5–§6 |
| OTP | Hashed OTP, expiry, attempt/resend limits; **dev mode displays OTP on screen**; SMS adapter pluggable | TSD §13 |
| Hosting (interim) | **Render** (API + worker + Postgres) + **Vercel** (Next.js) from repo config; Azure IaC later | Product Owner option (a); TSD §79–§81 |
| Branding | Light blue `#2E8BC9` family + gold `#C9A227` family; institutional, calm | Product Owner |

---

## 3. Conflicts and gaps found in the source documents

| # | Conflict / gap | Where | Recommended resolution |
|---|---|---|---|
| C1 | The **Opportunity state machine** begins at `DRAFT → PROFILE_IN_PROGRESS → … → CONSENTED → QUALIFIED`, but FSD-OPP-002 says an Opportunity ID is generated only *at* qualification, and Skill §33 begins the lifecycle at `QUALIFIED`. | FSD §44.1, §27; TSD §31; Skill §33 | Split into two server-enforced machines: the **Financial Need / Journey** carries `DRAFT … CONSENTED` (matches TSD §7 journey states), and the **Opportunity** entity is born at `QUALIFIED`. A read-model "Marketplace Pipeline" composes both so the full FSD pipeline is still reportable end to end. |
| C2 | **Appetite lifecycle** differs: FSD ends `EXPIRED / ARCHIVED`; Skill ends `EXPIRED / CLOSED`; capacity states (`ACTIVE/LIMITED/FULL/PAUSED`) are mixed into the lifecycle. | FSD §44.4, FSD-APP-001; Skill §27; TSD §24 | Two orthogonal fields: `lifecycle_status` = DRAFT, SIMULATED, APPROVED, ACTIVE, PAUSED, EXPIRED, ARCHIVED (FSD wins); `capacity_state` = ACTIVE, LIMITED, FULL, PAUSED (TSD §24), computed from configured limits plus manual override. |
| C3 | **Dispute states**: FSD §44.6 has `DECIDED`; FSD §40 and TSD §46 list decision outcomes as states. | FSD §40, §44.6; TSD §46 | State = OPEN → UNDER_REVIEW → DECIDED → CLOSED (plus FURTHER_INVESTIGATION loop back to UNDER_REVIEW); `decision` enum = CHARGE_VALID, CHARGE_REVERSED, OPPORTUNITY_REPLACED. Satisfies both. |
| C4 | **FR numbering** differs between BRD (FR-001…032) and FSD (FR-001…040). | BRD §37; FSD §51 | The traceability matrix uses FSD FR IDs as primary and maps each BRD FR to them. |
| C5 | **Institution SSO**: TSD prefers Entra ID with MFA. No Entra tenant exists for V1 test. | TSD §13 | V1 ships email + password + **TOTP MFA** (mandatory for WEZA admins, configurable per institution), behind an `IdentityProvider` interface so Entra ID OIDC can be added without changing domain code. |
| C6 | **Azure services** (Service Bus, Blob, Key Vault, API Mgmt) are not available on the interim host. | TSD §4, §51, §54, §58 | Interface-first adapters: `EventBus` (Postgres outbox now → Service Bus later), `ObjectStore` (Postgres large-object/local volume now → Blob later), `SecretStore` (platform env vars now → Key Vault later). The API layer provides gateway concerns (rate limit, validation, correlation ID). Azure Bicep/Terraform is delivered as IaC but not deployed in V1-test. |
| C7 | **Malware scanning** requires a scanner service (e.g. ClamAV/Defender for Storage). | TSD §42 | Pipeline state machine fully implemented; the `MalwareScanner` adapter in V1-test performs type/magic-byte/size validation and EICAR detection and is labelled `SCANNER=BASIC`. A production scanner is a deployment prerequisite (tracked as a go-live blocker). |
| C8 | **Mobile technology**: TSD says React Native *or equivalent*; the Product Owner has asked for Flutter. | TSD §4 | Flutter is an "equivalent" — no conflict with the spec. Scope proposed in §4 below. |
| C9 | BRD lists "Multi-Match" routing; Skill lists `MULTI_OPTION`, `INSTITUTION_INTEREST`, `EXCLUSIVE_WINDOW`, `CAMPAIGN_SPECIFIC`. | BRD §29; Skill §40 | Routing strategy is a configured enum per country/campaign. V1 enables `CUSTOMER_SELECTED` and `MULTI_OPTION` (max 3 institutions, separate consent each). Others are modelled and feature-flagged off. |

---

## 4. Scope agreed with the Product Owner

**Built completely (Phases 0–6):** foundation, auth, tenancy, audit · customer conversation (web + WhatsApp simulator), intent, OTP, profile, Financial Need · institution onboarding, Product Studio, Appetite Studio, simulator, activation · Rules Engine, Match Engine, customer marketplace, consent · Qualified Opportunity saga, routing, Opportunity Feed, Opportunity 360, My Day · notifications, outcome reporting, Manager view, Command Centre · commercial attribution, billing events, disputes · WEZA Admin Network Control Centre, Graph Inspector, Human Control Centre.

**Built in simpler but working form (Phases 7–8):** Customer Waiting Room · Institution Mandate Waiting · No-Lead Intelligence and Opportunity Radius · event-driven Market Clearing · Opportunity Preview + Institution Interest (feature-flagged) · Product Gap board · Conversational Institutional AI (tool-based, read-only).

**Flutter app (proposed scope for approval):** the customer app: start/resume conversation, OTP sign-in, profile, match results with why/why-not, consent, submission tracking, Waiting Room notifications. Institutional users use the responsive web Command Centre in V1. *Delivered as source + Android APK built by CI.*

**Explicitly out of scope (BRD §39, TSD §83):** core-banking/CRM/LOS integration, holding or moving funds, autonomous credit decisions, BNPL/payments/insurance/savings transactions.

---

## 5. What I need from you to approve

1. Approve or amend the conflict resolutions C1–C9.
2. Approve the Flutter scope in §4 (customer app only for V1).
3. Approve the interim hosting plan in [13-deployment.md](13-deployment.md).
4. **Before implementation:** this machine has no Python or Flutter SDK. I will install Python 3.12 and the Flutter SDK (user-level installs via `winget`) for local testing. CI on GitHub Actions also runs every test.
