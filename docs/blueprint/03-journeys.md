# 03 — Journey Maps

Each journey stage shows: what the actor does → what WEZA does → the graph node(s) → the emotional/decision moment → the controls that protect it.

## 1. Customer journey (BRD §6, §41; FSD §53)

| # | Stage | Customer | WEZA | Graph node (G1) | Moment of truth | Controls |
|---|---|---|---|---|---|---|
| 1 | Discover | Sees QR / link / partner post | Captures `src/cmp/ptn` attribution | START | "Is this legitimate?" | Clear "WEZA is not a lender" message, institution logos only for ACTIVE institutions |
| 2 | Start | "I need UGX 30M to expand my pharmacy" | Canonical message → session → journey graph | UNDERSTAND_INTENT | Effortless start | Rate limit per phone/IP; prompt-injection defence |
| 3 | Understand | Answers 1–2 clarifying questions | Intent Engine extracts fields + confidence | ASK_MISSING_INTENT ↺ | "It understood me" | Low-confidence fields require confirmation |
| 4 | Confirm intent | Taps **Yes** / edits | Facts marked CONFIRMED | CONFIRM_INTENT | Control | No matching before confirmation (FSD-INT-003) |
| 5 | Verify | Enters phone, OTP | OTP challenge, hashed | VERIFY_PHONE | Trust | Attempts/expiry/resend limits; dev display mode |
| 6 | Profile | Answers dynamic questions | Question path by customer type × need | BUILD_PROFILE ↺ | "Only relevant questions" | Never re-ask confirmed facts; provenance |
| 7 | Readiness | — | Readiness + Quality Score | READINESS_CHECK | — | Deterministic, versioned |
| 7a | Almost ready | Uploads document / gives missing item | Document pipeline | REQUEST_MISSING_ITEM ↺ | Guidance | Scan before use |
| 7b | No match | Opts in to wait | Waiting Room (G5) | WAITING_ROOM | Hope without false promise | Expiry + reconfirmation |
| 8 | Match | Sees ranked options + reasons | Rules + Match + ranking | MATCH → PRESENT_OPTIONS | Comparison | "Match is not approval" |
| 9 | Prefer | Adjusts preferences | Re-rank within eligibility | PRESENT_OPTIONS | Agency | Preference never overrides eligibility |
| 10 | Select | Chooses Institution B | Match → SELECTED | CUSTOMER_SELECTS | Commitment | Re-validate match freshness |
| 11 | Consent | Reviews scope, agrees | Consent record (versioned) | CONSENT | Informed choice | Exact text hash stored |
| 12 | Submit | — | Qualified Opportunity saga (G3 entry) | CREATE_OPPORTUNITY | — | Duplicate/integrity checks, idempotency |
| 13 | Confirm | Sees reference + next steps | Notifies customer | CONFIRM | Reassurance | Shown only after ROUTED |
| 14 | Track | Gets status updates | Mirrors institution-reported status | TRACKING | Transparency | Never invent bank statuses (BRD §33) |
| 15 | Outcome | Approved / declined | If declined → offer rescue (G7) | — | Resilience | New consent per institution |

**Exit/failure paths:** abandon at any node → graph `PAUSED_BY_CUSTOMER` with `next_action_at` reminder (max 2 reminders) → `EXPIRED` after 14 days. Consent declined → back to options. Customer closes need → `CLOSED`.

## 2. Institution journey (BRD §42; FSD §16–27)

| # | Stage | Institution actor | WEZA | Graph (G2/G6/G3) | Controls |
|---|---|---|---|---|---|
| 1 | Join | Representative submits application | Institution `SUBMITTED` | G2 START | Terms version recorded |
| 2 | Verify | — (WEZA Ops reviews) | `UNDER_VERIFICATION` → `APPROVED` | VERIFY_INSTITUTION (human) | Maker: Ops; reason required |
| 3 | Workspace | Admin logs in, enrols MFA | Tenant provisioned | CREATE_WORKSPACE | Tenant isolation |
| 4 | Users | Invites team, assigns roles | Users + roles | CONFIGURE_USERS | ≥ 1 admin + ≥ 1 officer |
| 5 | Product | Business lead configures or extracts by AI | Product DRAFT | CONFIGURE_PRODUCT | AI proposals = drafts |
| 6 | Approve product | Approver (≠ author) approves | Product ACTIVE (version) | APPROVE_PRODUCT (human) | Maker-checker |
| 7 | Appetite | Credit lead sets mandate | Appetite DRAFT | CONFIGURE_APPETITE | — |
| 8 | Simulate | Runs simulator | Aggregate results | SIMULATE → REVIEW | k-anonymity |
| 9 | Approve appetite | Approver | Appetite APPROVED | APPROVE_APPETITE (human) | Maker-checker |
| 10 | Routing | Configures rules + service targets | Routing config | CONFIGURE_ROUTING | Fallback = Unassigned |
| 11 | Notifications | Sets preferences | Prefs | CONFIGURE_NOTIFICATIONS | Defaults pre-filled |
| 12 | Sandbox | Tests with synthetic customers | Sandbox run | (optional) | No billing |
| 13 | Activate | Admin clicks ACTIVATE ON WEZA | Institution ACTIVE; appetite ACTIVE | READINESS_CHECK → ACTIVATE | All checks pass |
| 14 | Receive | Officers get opportunities | Routing + assignment | G3 ROUTED → ASSIGNED | Consent-bound disclosure |
| 15 | Prioritise / contact | Officer contacts customer | Service-target clock | G3 CONTACTED | Escalation |
| 16 | Internal process | Institution's own KYC/credit (outside WEZA) | — | PROCEEDING / SUBMITTED | Zero integration |
| 17 | Report outcome | One-tap outcome | Outcome + commercial + learning | REPORTED_* | Labelled "reported" |
| 18 | Learn | Reviews insights, simulates changes | Insights, radius | G6 | No auto-changes |

## 3. WEZA Admin journey (FSD §41)

| Stage | Admin | WEZA | Controls |
|---|---|---|---|
| Morning check | Opens Network Control Centre | Liquidity, health, queues, failures | — |
| Verify institutions | Reviews applications | Advances G2 | Reason + audit |
| Human Control Centre | Works through review queue (low-confidence AI, conflicts, integrity, routing failures, dead letters) | Resumes interrupted graphs | Each decision audited |
| Investigate | Graph Inspector on an opportunity | Full lineage, decisions, versions | Read access audited |
| Disputes | Decides dispute | Reversal/credit event, not mutation | Evidence retained |
| Network control | Pauses institution/product/mandate or routing | Kill switch → clearing re-run, customers re-matched | Reason mandatory, MFA re-prompt |
| Configure | Edits country config / weights / flags | New version | Versioned, effective-dated |
| Support | Finds customer via vault lookup | Masked data, reason captured | Audited |
