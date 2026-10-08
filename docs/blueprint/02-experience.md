# 02 — Experience: IA, Sitemap, Screens, Design System, Wireframes

## 1. Information architecture

Three audiences, three mental models:

| Audience | Mental model | Organising principle |
|---|---|---|
| Customer | "I have a goal and need money for it." | **One conversation**, a few moments of decision (confirm intent, verify, choose, consent) and a status tracker. No menus during the journey. |
| Institution | "Find me the customers I want and tell me what needs my attention." | **Attention first** (Command Centre, My Day, Feed). Configuration (Products, Appetite, Routing) is secondary navigation. Intelligence is a third tier. |
| WEZA Admin | "Is the network healthy, fair and safe?" | **Control centre + queues** (verification, human review, disputes, integrity), then inspection (Graph Inspector, audit), then configuration. |

Navigation for the institution portal is grouped as **Work** / **Supply** / **Intelligence** / **Workspace**. Items appear only if the role has the permission. The server still enforces every permission; the UI filter is cosmetic only.

## 2. Sitemap

```text
PUBLIC & CUSTOMER  (apps/web, Flutter mirrors /c/*)
/                         Landing (Tell WEZA what financing you need) ?src=&cmp=&ptn=
/for-institutions         Institution proposition + "Join WEZA"
/start                    Conversation (web channel)
/whatsapp-sim             WhatsApp simulator (dev/test only, feature-flagged)
/c/verify                 Phone + OTP
/c/profile                Profile review & correct (provenance chips)
/c/documents              Document upload
/c/matches                Match results (options, why / why-not, preferences)
/c/matches/[matchId]      Institution/Product detail
/c/consent/[matchId]      Consent (institution, purpose, data categories, version)
/c/submitted/[oppId]      Submission confirmation
/c/status                 My needs & opportunities tracker (+ withdraw consent)
/c/waiting-room           Waiting Room status / opt-in / reconfirm
/c/preferences            Contact channel & window, ranking preferences
/legal/consent/[ver]      Published consent text versions

INSTITUTION  (/institution)
/institution/join                      Join WEZA (application)
/institution/login                     Login (+ MFA)
/institution/onboarding                Activation checklist (graph-driven)
  Work
/institution                           Command Centre
/institution/my-day                    Officer My Day
/institution/feed                      Opportunity Feed
/institution/opportunities/[id]        Opportunity 360
/institution/previews                  Opportunity Previews + Interest (flag)
/institution/team                      Team Manager view
  Supply
/institution/products                  Product Studio list
/institution/products/new|[id]         Product editor / detail / versions / approve
/institution/products/extract          AI product extraction (upload → draft)
/institution/appetite                  Appetite Studio list
/institution/appetite/new|[id]         Appetite editor / versions / approve / activate
/institution/appetite/[id]/simulate    Simulator
/institution/sandbox                   Configuration sandbox (synthetic customers)
  Intelligence
/institution/radius                    Opportunity Radius / No-lead intelligence
/institution/demand                    Demand Intelligence (Pulse, map, distributions)
/institution/product-opportunity       Product Gap board
/institution/insights                  Appetite/outcome insights (review queue)
/institution/ask                       Conversational WEZA
/institution/reports                   Outcomes & reports
  Workspace
/institution/users                     Users & Roles
/institution/routing                   Routing rules & service targets
/institution/notifications             Notification preferences
/institution/billing                   Contract, subscription, billing events, disputes
/institution/audit                     Compliance: consent & access log
/institution/settings                  Institution profile, verification status

ADMIN  (/admin)
/admin                                 Network Control Centre
/admin/institutions                    Applications & verification queue; management
/admin/institutions/[id]               Institution detail + kill switches
/admin/market                          Market State & liquidity / health
/admin/opportunities                   Opportunity monitoring (routing, stale, unassigned)
/admin/customers                       Customer support (search by token / phone via vault w/ reason)
/admin/review                          Human Control Centre queue
/admin/integrity                       Integrity cases
/admin/disputes                        Commercial disputes
/admin/commercial                      Contracts, billing events, unit economics
/admin/graph                           Graph Inspector (search by any node)
/admin/audit                           Audit & consent ledger
/admin/notifications                   Delivery failures, dead letters, replay
/admin/config                          Country config, consent templates, question paths, weights, feature flags, kill switches, AI mode
```

## 3. Screen inventory (FSD §50 + Skill additions)

| ID | Screen | Role | FSD/BRD ref |
|---|---|---|---|
| C-01 | Landing | Public | FSD-CUS-001/002, BRD §5 |
| C-02 | Conversation (web) | Customer | FSD §4–6 |
| C-03 | WhatsApp simulator | Tester | TSD §5–6 |
| C-04 | OTP | Customer | FSD-IDV-001 |
| C-05 | Profile review | Customer | FSD §8, FSD-PRO-002 |
| C-06 | Document upload | Customer | FR-005, TSD §42 |
| C-07 | Match results | Customer | FSD §12 |
| C-08 | Institution / product detail | Customer | FSD-MKT-001/003 |
| C-09 | Consent | Customer | FSD §13 |
| C-10 | Submission confirmation | Customer | FSD §14 |
| C-11 | Status tracker | Customer | BRD §33 |
| C-12 | Waiting Room | Customer | FSD-WAIT-001 |
| C-13 | Preferences | Customer | FSD-CON-003, FSD-MKT-002 |
| I-01 | Join WEZA | Applicant | FSD §16 |
| I-02 | Login + MFA | Inst. user | TSD §13 |
| I-03 | Activation checklist | Inst. admin | FSD §21 |
| I-04 | Command Centre | All inst. roles | FSD §22 |
| I-05 | My Day | Officer | FSD §26 |
| I-06 | Opportunity Feed | Officer/Manager | FSD §23 |
| I-07 | Opportunity 360 | Officer/Manager/Compliance | BRD §17 |
| I-08 | Previews & Interest | Business/Credit | FSD §24 |
| I-09 | Team Manager | Manager | FSD §26 |
| I-10 | Product Studio list / editor / approve | Business, Admin approver | FSD §19 |
| I-11 | AI product extraction | Business | FSD §18 |
| I-12 | Appetite Studio list / editor / approve | Credit/Risk | FSD §20 |
| I-13 | Simulator | Credit/Risk, Exec | FSD-APP-002 |
| I-14 | Sandbox | Admin, Business, Credit | BRD §34.7, TSD §74 |
| I-15 | Opportunity Radius / No-lead | Business, Credit, Exec | FSD §28 |
| I-16 | Demand Intelligence | Exec, Business | FSD §30 |
| I-17 | Product Opportunity board | Business, Exec | FSD §31 |
| I-18 | Insights review | Credit/Risk | FSD §35 |
| I-19 | Conversational WEZA | All (scoped) | FSD §32 |
| I-20 | Outcomes & reports | Manager, Exec | FSD §27 |
| I-21 | Users & Roles | Inst. admin | FSD §17 |
| I-22 | Routing & service targets | Inst. admin, Manager | FSD §25 |
| I-23 | Notification preferences | All (own), Admin (org) | FSD §33 |
| I-24 | Billing & disputes | Inst. admin, Exec | FSD §39–40 |
| I-25 | Compliance audit | Compliance | FSD §17 |
| A-01 | Network Control Centre | WEZA Ops | FSD §41 |
| A-02 | Institution verification & management | WEZA Ops | FSD §16, §41 |
| A-03 | Market State & health | WEZA Ops | Skill §10, §38 |
| A-04 | Opportunity monitoring | WEZA Ops | FSD §41 |
| A-05 | Customer support | WEZA Support | FSD §41 |
| A-06 | Human Control Centre | WEZA Ops | Skill §59 |
| A-07 | Integrity cases | WEZA Ops | FSD §38 |
| A-08 | Disputes | WEZA Commercial | FSD §40 |
| A-09 | Commercial & unit economics | WEZA Commercial | TSD §43, §78 |
| A-10 | Graph Inspector | WEZA Ops | Skill §59 |
| A-11 | Audit & consent ledger | WEZA Compliance | FSD §42 |
| A-12 | Notifications & dead letters | WEZA Ops | TSD §57 |
| A-13 | Configuration & kill switches | WEZA Super-admin | TSD §71, §75 |

## 4. Screen-by-screen specification (Skill §70)

Format: **Objective · Entry · Data · Primary / Secondary actions · Empty · Loading · Error · Permission · Notifications · Audit · Mobile · Acceptance criteria.** All screens share these defaults: skeleton loaders while data loads; an error state with a safe message and correlation ID plus "Try again"; a 403 state saying "You don't have access to this — ask your administrator", with no data leaked.

### C-01 Landing
- **Objective:** start a financing conversation in one tap. **Entry:** web, QR, partner link (`?src&cmp&ptn`).
- **Data:** none personal. Attribution params are captured into a signed `attribution` cookie and sent on session start.
- **Primary:** text box "Tell WEZA what you need financing for" → `/start`. **Secondary:** "Continue on WhatsApp" (click-to-chat link), "For institutions".
- **Empty/Error:** n/a. **Audit:** `SessionStarted` with source. **Mobile:** single column, input sticky at bottom.
- **AC:** attribution persisted to session → need → opportunity → commercial event (FSD-CUS-001). Copy never promises a loan.

### C-02 Conversation
- **Objective:** turn natural language into a structured, confirmed Financial Need and a complete profile, asking only the next needed question.
- **Entry:** Landing, resume link, app. **Data:** journey graph state, intent fields with confidence, next question.
- **Primary:** reply (text or quick-reply buttons). **Secondary:** "Edit what WEZA understood" panel, "Save & exit".
- **Components:** message list; **Understanding card** (amount, purpose, customer type, sector, each marked *confirmed / needs confirmation*); quick replies; progress indicator (Need → Verify → Profile → Options).
- **Empty:** welcome prompt "Welcome to WEZA. Tell me what you would like financing for." (FSD-CUS-002).
- **Error:** AI unavailable → automatically switches to structured questions (banner "Simple mode"). Network failure → message queued with retry.
- **Audit:** messages stored as canonical messages; facts with provenance. **Mobile:** full-screen chat.
- **AC:** "I need UGX 30 million to expand my pharmacy" yields amount 30,000,000 UGX, purpose expansion, type SME, sector pharmacy/health, and asks for confirmation before matching (FSD-INT-003). A confirmed question is never re-asked (Skill §17). A returning verified customer is offered resume (FSD-CUS-003).

### C-03 WhatsApp simulator
- Phone-frame UI that posts to the same webhook gateway the real WhatsApp webhook uses (canonical message contract). Shows button replies as WhatsApp interactive buttons. Feature flag `channel.whatsapp_simulator`. **AC:** the same journey completes via simulator and via web, and both produce identical graph states.

### C-04 OTP
- **Objective:** verify a reachable phone. **Data:** phone (country rules), OTP challenge status, attempts left, resend cooldown.
- **Primary:** Send code → Enter 6 digits → Verify. **Secondary:** change number, resend (after cooldown).
- **Errors (FSD-IDV-001):** Incorrect (attempts left shown) · Expired (offer resend) · Max attempts (locked 15 min) · Delivery failure (offer retry/alternative channel).
- **Dev mode:** with `OTP_DELIVERY=display`, the code is shown in a dev banner. The banner is never shown in production config.
- **Audit:** `PhoneVerificationRequested/Succeeded/Failed` (no OTP values). **AC:** OTPs stored only as salted hashes, 5-minute expiry, 5 attempts, 3 resends per 15 minutes, IP + phone rate limits.

### C-05 Profile review
- **Objective:** let the customer see and correct what WEZA holds before routing (FSD-PRO-002).
- **Data:** facts grouped (About you / Business or Employment / Finances / Need), each with a provenance chip (*You told us · WhatsApp · 2 Oct* / *Read from document* / *Needs confirmation*).
- **Primary:** Confirm profile. **Secondary:** edit a fact. **AC:** editing a material fact after matching invalidates affected matches (G4/§21) and shows "Your options will be refreshed".

### C-06 Document upload
- **Objective:** provide required supporting documents. **Data:** requirement checklist driven by the union of matched products' requirements.
- **States per file:** Uploading → Checking (quarantine/scan) → Accepted / Rejected (reason). **AC:** raw files are never sent to an LLM before scan passes (TSD §42), max 10 MB, PDF/JPG/PNG only.

### C-07 Match results
- **Objective:** choose a suitable option. **Data:** ranked matches (institution, product, amount range, indicative tenor, approved cost info, key requirements, *why matched* chips, readiness).
- **Primary:** Choose this option → C-09. **Secondary:** View detail, change preferences (re-ranks within eligibility), "Why not other options?", "Keep looking" (Waiting Room).
- **Empty / NO_CURRENT_MATCH:** "No participating institution currently matches this need" + reasons in plain language + Waiting Room opt-in. Never invents an institution (FSD §45).
- **ALMOST_READY:** a banner lists the exact missing item(s) with a CTA.
- **Labels:** "Match reflects how well your need fits this institution's current criteria. It is **not** a loan approval." (BR-002). Sponsored placements (if ever enabled) carry a visible "Sponsored" label and sit in a separate slot (BR-008).
- **AC:** only ACTIVE institution + ACTIVE product + ACTIVE appetite with capacity ≠ FULL/PAUSED appear. Stale/invalidated matches are never shown.

### C-08 Institution / product detail
- Product terms, requirements, institution profile, full match explanation (matched / near-miss / requirements outstanding). Confidential rule thresholds of the institution are not revealed (FSD-MKT-003).

### C-09 Consent
- **Objective:** an explicit, institution-specific, informed decision. **Data:** consent template (versioned), institution, purpose, data categories (Contact details, Identity, Business/Employment profile, Financial information, Documents), contact preference/window.
- **Primary:** "I agree — share with {Institution}". **Secondary:** Decline (journey returns to options; nothing shared).
- **AC:** consent record stores template version + hash of the exact text shown. No Level-3 disclosure without it (BR-001). Copy states that the institution does its own KYC and credit decision and that the phone number is not a disbursement destination (BR-003, BR-007).

### C-10 Submission confirmation
- Opportunity reference, institution, what happens next, expected first-contact window (institution service target), how to withdraw. **AC:** shown only after the saga reaches ROUTED. If routing fails, the customer sees "We're re-checking your options" (FSD-OPP-005).

### C-11 Status tracker
- Timeline of marketplace states **as reported by the institution**, labelled "Reported by {Institution}" (BR-005). Withdraw consent / close need. Non-response escalation message after the service target is breached (BRD §33).

### C-12 Waiting Room
- Opt-in with an expiry (default 30 days, country-configurable), reconfirmation reminder at day 25, "notify me on WhatsApp/SMS". On a new match: "A new option may fit your need — review it" (no disclosure until consent).

### C-13 Preferences
- Contact channel, contact window, ranking preferences (lower monthly payment, longer tenor, lower collateral, digital journey, near me, faster response).

### I-01 Join WEZA
- Multi-step application: legal name, institution type (from country config), licence/regulator & number, authorised representative, business contact, compliance contact, accept marketplace terms (version). Creates Institution `SUBMITTED` and the onboarding graph. **AC:** no portal access to opportunities until APPROVED and ACTIVE.

### I-02 Login + MFA
- Email + password → TOTP (if enrolled/required). Lockout after 5 failures/15 min. Forced MFA enrolment for institution admins and all WEZA admins.

### I-03 Activation checklist
- Rendered from the Institution Onboarding graph state: Verified ✓ · Users ✓ · Product approved · Appetite active · Routing · Notifications · Terms · Sandbox test (recommended) → **ACTIVATE ON WEZA** (enabled only when the graph's READINESS_CHECK passes). Each unmet item deep-links to its node (Skill §25).

### I-04 Command Centre
- **Objective:** "What requires my attention?" **Top:** *Briefing* sentence generated from deterministic aggregates, e.g. "74 new opportunities matched your active mandates since yesterday. UGX 1.84B requested. 19 exceed 90% match. 3 high-value opportunities remain unassigned." Then an **Attention list** (unassigned high-value, service targets approaching/breached, customers waiting). Then FSD-CMD-001 cards: New, Qualified Demand, High Match, Contacted, Progressing, Reported Approved, Reported Disbursed, Avg Response Time, Conversion, Unassigned, Customers Waiting.
- **Role personalisation (FSD-CMD-002):** Officer sees own queue; Manager sees team; Exec sees value/progression/demand; Credit sees appetite performance; Compliance sees consent/access stats.
- **Empty (no opportunities):** No-lead intelligence card linking to Radius (BR-010).

### I-05 My Day (Officer)
- Ordered work list: new assigned · high-match · follow-ups due · approaching targets · waiting customers. Each row: countdown, next action button (Contact / Update outcome). Ordering is explainable ("Sorted by: target due, match, value").

### I-06 Opportunity Feed
- Columns per FSD §23: priority, match %, need, amount, sector, location (district), readiness, age/freshness, why matched, owner, next action. Filters, saved views. Actions: View, Assign, Contact, Request Info, Interested/Not Interested (previews), Report Outcome. "Ranked by" explainer popover (FSD-FED-001).

### I-07 Opportunity 360
- Sections: Financial need · Customer (only consented fields, served via the Disclosure Gateway; restricted fields show "Not shared under this consent") · Business/employment profile · Match intelligence (score components, matched/near-miss, versions) · Quality score factors · Authorised documents (short-lived links) · Consent (scope, version, timestamp, status) · Activity timeline · Assignment & service target · Outcome panel (one-tap: Contacted / Proceeding / Submitted / Reported Approved {amount} / Reported Declined {reason} / Withdrawn / Reported Disbursed {amount, date}).
- **Audit:** every view of identifiable data writes `OpportunityViewed` with the fields disclosed. **AC:** after consent withdrawal, identifiable fields disappear for new views. Data already received is acknowledged in the copy (FSD-CON-002).

### I-08 Previews & Interest (flag `marketplace.preview`)
- Non-identifiable cards: segment, sector, region (not district if k < 5), amount band, business-age band, match band. Actions: Interested / Need more information / Not interested. **AC:** Preview payloads are produced by a separate serializer with an allow-list of fields, verified by a test.

### I-09 Team Manager
- Distribution by officer, contact rate, ageing buckets, breaches, workload; bulk reassign; uncontacted high-match list.

### I-10 Product Studio
- List with status chips (DRAFT, PENDING_APPROVAL, ACTIVE, PAUSED, ARCHIVED) and versions. Editor groups per FSD §19: Identity, Terms, Eligibility (rule builder: field · operator · value, with field catalogue from the profile schema), Requirements (documents), Governance (owner, approver, effective dates).
- Submit for approval → an approver with `product.approve` (not the author: **maker-checker** [Design Recommendation]) approves → ACTIVE. Editing an ACTIVE product creates a new DRAFT version; the active version continues until the new one is approved.

### I-11 AI product extraction
- Upload approved product document → scanned → AI proposes product fields + rules with **provenance** (page/quote) and confidence → user edits → saves as DRAFT. Banner: "AI proposals are drafts. Nothing is active until approved." (FSD §18).

### I-12 Appetite Studio
- Fields per FSD §20: product(s), segment, ticket range, sectors, regions/districts, business age / employment duration, turnover/income floor, target count or value, campaign dates, minimum match score, capacity limits (daily/weekly/monthly count and value), service targets. Lifecycle per C2. Simulation is **required** before approval [per Skill §27 lifecycle].

### I-13 Simulator
- Runs proposed criteria over permitted anonymised demand (last N days active + waiting needs). Output: potential matches, requested value, match-band histogram, top near-miss reasons with counts, district/sector distribution (k ≥ 5). Compare with the current version side by side. **AC:** never returns identities; result stored as `simulation_run` and attached to the appetite version.

### I-14 Sandbox
- Generates synthetic customers (tagged `synthetic=true`, separate partition). Runs matching + routing against the institution's draft configuration and shows which synthetic customers would route where and why. **AC:** synthetic data cannot create billing events or notifications to real users.

### I-15 Opportunity Radius / No-lead
- Three zones: Inside / Near / Outside appetite, with counts and value, plus "near because of" rules (e.g. "UGX 2.4B of SME demand misses only your minimum-turnover rule"). CTA: "Simulate a change" (→ I-13, prefilled). Never auto-loosens criteria.

### I-16 Demand Intelligence
- Demand by region/district (choropleth-style list/map), sector, customer type, purpose, ticket distribution, readiness, match bands, trend (weekly). All k-anonymised.

### I-17 Product Opportunity board
- Unmet-demand clusters (e.g. solar-equipment financing), coverage ratio, near-match demand, "Simulate hypothetical product". Decision support only.

### I-18 Insights review
- Appetite/outcome mismatch insights (FSD §35), e.g. "23 customers meeting your turnover threshold were reported declined for insufficient turnover." Actions: Dismiss (reason) / Simulate change / Create draft appetite version (still requires approval).

### I-19 Conversational WEZA
- Chat over approved tools only (TSD §36). Shows which tool was called and the structured result under each answer. Read-only: it can *prepare* a simulation, never apply it.

### I-20 Outcomes & reports
- Funnel by stage, conversion, reported approvals/disbursements (labelled *reported*), decline reasons, response times; export CSV (audited).

### I-21 Users & Roles · I-22 Routing · I-23 Notifications · I-24 Billing · I-25 Compliance audit
- Users: invite, role(s), team, status, MFA status. Routing: ordered rules (if product/amount/sector/region → team/user), fallback = Unassigned, service targets (acknowledge within X h, first contact within Y h). Notifications: per event × channel × priority matrix. Billing: contract terms, billing events, dispute button per event (within the dispute window). Compliance: consent ledger and data-access log for the tenant.

### A-01 … A-13 Admin
- **Network Control Centre:** liquidity state per segment (HIGH/MEDIUM/LOW/ILLIQUID), demand vs. supply, routing success, unassigned/stale, notification failures, open queues, kill-switch status.
- **Verification:** application review checklist (licence checked, representative verified), approve/reject with reason → institution graph advances.
- **Human Control Centre:** unified queue of interrupts: low-confidence AI, fact conflicts, integrity REVIEW, routing failures, disputes, repeated graph failures, dead letters. Each item links to the Graph Inspector.
- **Graph Inspector:** search any ID → renders the Customer → Need → Match → Consent → Opportunity → Institution → Officer → Outcome graph, with versions, events, decisions (Decision Ledger), agent/tool calls, retries and current graph nodes.
- **Customer support:** looks up a customer by phone through the Identity Vault. This requires a reason, is audited and shows masked data by default.
- **Config:** country config, consent templates (versioned, never AI-edited), question paths, match weights (versioned), feature flags, kill switches (Pause All Routing, Suspend Institution, Pause Product, Pause Mandate, Disable channel, AI mode AVAILABLE/DEGRADED/UNAVAILABLE, Pause billing-event creation), all audited with a reason.

## 5. Design system

### 5.1 Direction
Premium financial infrastructure: calm, institutional, high-trust, with generous whitespace, strong typography, restrained colour and purposeful charts. No neon, no glassmorphism, no cartoon illustration. The colours are light blue as the primary trust/action colour and **gold reserved for meaning**: high match, value, success highlights and brand accents. Gold is never used for errors.

### 5.2 Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--brand-blue-50` | `#EEF7FD` | `#0F2233` | tinted surfaces |
| `--brand-blue-100` | `#D6ECFA` | `#14324A` | selected rows |
| `--brand-blue-400` | `#5AAEE3` | `#5AAEE3` | charts, focus |
| `--brand-blue-600` | `#2E8BC9` | `#6DB8E8` | primary actions/links |
| `--brand-blue-800` | `#1B5E8C` | `#A9D6F3` | headings accent |
| `--brand-navy-900` | `#0E2A3F` | `#E8F1F8` | primary text |
| `--brand-gold-100` | `#FBF3DC` | `#2E2610` | highlight surface |
| `--brand-gold-500` | `#C9A227` | `#D9B647` | high match, value, brand mark |
| `--brand-gold-700` | `#8F7012` | `#E6CB72` | gold text on light |
| `--surface` | `#FFFFFF` | `#0B1620` | cards |
| `--canvas` | `#F6F9FC` | `#07111A` | page |
| `--border` | `#DCE5EE` | `#1E3242` | dividers |
| `--muted` | `#5B6B7A` | `#8FA3B5` | secondary text |
| `--success` | `#1F8A5B` | `#3CC48A` | reported approved/disbursed |
| `--warning` | `#B7791F` | `#E0A54A` | attention required |
| `--danger` | `#C0392B` | `#E5675A` | breach, error |

**Type:** *Inter* for UI (tabular numbers for amounts), *Source Serif 4* for briefing headlines (adds editorial calm). Scale 12/14/16/20/24/32/40. **Radius** 8 px for controls, 12 px for cards. **Elevation:** border plus a 1-level shadow only. **Spacing:** 4-pt grid.

### 5.3 Components (shared, in `apps/web/components/ui` and mirrored in Flutter)
AppShell (sidebar + topbar + tenant badge) · Briefing · StatCard · AttentionList · DataTable (sort, filter, saved views) · OpportunityRow · MatchScore (ring 0–100, gold ≥ 90) · ScoreBreakdown (component bars) · ReasonChips (matched ✓ / near ~ / missing !) · ProvenanceChip · ReadinessBadge (READY_NOW/ALMOST_READY/NO_CURRENT_MATCH) · FreshnessBadge · StateTimeline · Countdown (service target) · RuleBuilder · VersionHistory · DiffView · ApprovalBar (maker-checker) · ConsentCard · ChatThread / QuickReplies / UnderstandingCard · OTPInput · Uploader · EmptyState (with intelligence slot) · Banner (AI mode, sandbox, dev OTP) · KillSwitch · GraphCanvas (inspector) · Toasts · Dialog · Tabs · Skeleton.

**Accessibility:** WCAG 2.2 AA contrast for all text tokens. Focus rings use `--brand-blue-400`. Every chart has a table alternative. All interactive elements are keyboard reachable. Touch targets are at least 44 px.

## 6. Desktop wireframes (institution)

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ WEZA ◆  Lakeside Bank · SME Banking                 🔔 3   Ask WEZA…   (AK)│
├────────────┬─────────────────────────────────────────────────────────────────┤
│ WORK       │ Good morning, Amina.                                            │
│ ▸ Command  │ 74 new opportunities matched your active mandates since         │
│   My Day   │ yesterday — UGX 1.84B requested. 19 exceed 90% match.           │
│   Feed     │ 3 high-value opportunities are unassigned.                      │
│   Team     ├─────────────────────────────────────────────────────────────────┤
│ SUPPLY     │ NEEDS ATTENTION                                                 │
│   Products │ ● UGX 75M · SME Working Capital · Mbarara · 96% ◆  Unassigned  [Assign]
│   Appetite │ ● UGX 40M · Pharmacy expansion · Kampala · 92% ◆  Target in 2h [Open] │
│   Sandbox  │ ● 7 customers waiting > 24h for first contact             [View]│
│ INTELLIG.  ├───────────┬───────────┬───────────┬───────────┬────────────────┤
│   Radius   │ New   74  │ Demand    │ High ◆ 19 │ Contacted │ Reported       │
│   Demand   │ ▲12%      │ 1.84B     │           │ 41        │ Approved 9     │
│   Products │           │           │           │           │ Disbursed 6    │
│   Ask WEZA ├───────────┴───────────┴───────────┴───────────┴────────────────┤
│ WORKSPACE  │ Conversion by stage ▇▇▇▇▇▆▅▃▂   Avg first contact 3h 12m        │
│   Users …  │                                                                 │
└────────────┴─────────────────────────────────────────────────────────────────┘

Opportunity 360
┌──────────────────────────────────────────────────────────────────────────────┐
│ ← Feed   OPP-7F3K2  Pharmacy expansion · UGX 30,000,000      ASSIGNED ▸ Contact│
│ Fresh · Target: first contact in 2h 10m        Owner: J. Okello  [Reassign]  │
├───────────────────────────────┬──────────────────────────────────────────────┤
│ CUSTOMER (shared with consent)│ MATCH  92 ◆                                   │
│ Name   Grace N.               │ Product fit   ████████░ 0.94                  │
│ Phone  +256 7•• ••• 123 [Show]│ Appetite fit  ████████░ 0.90                  │
│ District Kampala              │ Readiness     █████████ 1.00                  │
│ Verified: Phone ✓  NIN ✓      │ Capacity      ███████░░ 0.80                  │
│ BUSINESS                      │ ✓ Amount within 5M–100M  ✓ Health sector      │
│ Pharmacy · 4 yrs · Reg. ✓     │ ✓ Business age ≥ 2y      ~ Turnover close     │
│ Turnover UGX 12M/m (self-rep.)│ Rules v7 · Appetite v5 · Algorithm m1.2       │
├───────────────────────────────┴──────────────────────────────────────────────┤
│ What happened with this customer?                                            │
│ [Contacted] [Proceeding] [Submitted] [Reported approved…] [Declined…] [Withdrawn]│
└──────────────────────────────────────────────────────────────────────────────┘
```

## 7. Mobile / customer wireframes (web + Flutter)

```text
┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐
│ WEZA ◆              │   │ ← Your options      │   │ ← Consent           │
│                     │   │ 3 institutions fit  │   │ Share with          │
│ Welcome to WEZA.    │   │ your need           │   │ Lakeside Bank       │
│ Tell me what you'd  │   │ ┌─────────────────┐ │   │                     │
│ like financing for. │   │ │Lakeside Bank  92◆│ │   │ Purpose: to contact │
│                     │   │ │SME Growth Loan  │ │   │ you about your      │
│      I need UGX 30M │   │ │5M–150M · 6–36 mo│ │   │ financing request   │
│  to expand my pharm.│   │ │✓ Amount ✓ Sector│ │   │                     │
│ ┌─────────────────┐ │   │ │✓ Business age   │ │   │ ☑ Contact details   │
│ │I understood:    │ │   │ │ [Choose]  Detail│ │   │ ☑ Business profile  │
│ │UGX 30,000,000 ✓ │ │   │ └─────────────────┘ │   │ ☑ Financial info    │
│ │Expand pharmacy ✓│ │   │ ┌─────────────────┐ │   │ ☑ Documents (2)     │
│ │Business (SME) ? │ │   │ │Pearl SACCO 85   │ │   │                     │
│ │[Yes] [Change]   │ │   │ │…                │ │   │ The bank does its   │
│ └─────────────────┘ │   │ Match is not a loan │   │ own checks and      │
│ [Type a message…] ➤ │   │ approval.           │   │ decision.  v2026.1  │
└─────────────────────┘   └─────────────────────┘   │ [I agree — share]   │
                                                    │ Not now             │
                                                    └─────────────────────┘
```
