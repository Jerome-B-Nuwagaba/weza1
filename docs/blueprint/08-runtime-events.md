# 08 — Graph Runtime, Event Architecture, Observability

## 1. Graph persistence model (Skill §48) [Design Recommendation: in-house runtime]

LangGraph is not used. WEZA's graphs are mostly deterministic, with interrupts lasting days and human approvals. Their state must be queryable SQL and auditable, so a small typed runtime (~400 lines) is simpler, safer and testable.

```sql
platform.graph_instance(
  id uuid pk, graph_type text, graph_version int, current_node text,
  state jsonb, status text check (status in ('RUNNING','WAITING','COMPLETED','FAILED','CANCELLED','EXPIRED')),
  waiting_for text null,            -- e.g. CUSTOMER_REPLY, OTP, CONSENT, HUMAN_APPROVAL, INSTITUTION_ACTION
  customer_id uuid null, institution_id uuid null, opportunity_id uuid null, need_id uuid null,
  attempt_count int, error_state jsonb null,
  next_action_at timestamptz null,  -- timer for timeouts/reminders
  created_at, updated_at, version int  -- optimistic concurrency
)
platform.graph_transition(id, instance_id, from_node, to_node, trigger, input_hash, actor, at, duration_ms, autonomy_level)
```

**Runtime contract**
- A graph = `GraphDef(type, version, nodes: dict[str, Node], start)`. `Node.run(ctx, state) -> Transition(to, state_patch, wait=None|Wait(kind, timeout, on_timeout))`.
- `advance(instance_id, trigger)` loads with `SELECT … FOR UPDATE`, runs nodes until a wait/terminal, persists state + transitions + outbox events **in the same transaction**, and bumps `version`.
- Interrupts: `resume(instance_id, kind, payload)` validates that `waiting_for == kind`.
- Timers: the worker polls `next_action_at <= now()` (`FOR UPDATE SKIP LOCKED`) and resumes with a `TIMEOUT` trigger, so no waiting node is ever unbounded.
- Version migration: instances keep their `graph_version`. New versions apply to new instances. A migration function per version pair moves live instances when needed (tested).
- Retry: node exceptions increment `attempt_count`, with exponential `next_action_at`. After the max → `FAILED` + Human Control Centre item.

## 2. Graph event model (Skill §23)

Every transition emits `GraphTransitioned{graph_type, instance_id, from, to, trigger, autonomy}` to the `workflow-events` topic (for the inspector and metrics), plus the domain events listed per graph in [05-graphs.md](05-graphs.md).

## 3. Event envelope

```json
{
  "event_id": "uuid-v7", "event_type": "OpportunityQualified", "event_version": 1,
  "topic": "opportunity-events", "occurred_at": "…", "producer": "core-api",
  "aggregate_type": "opportunity", "aggregate_id": "…", "institution_id": "…|null",
  "correlation_id": "…", "causation_id": "…", "data": { "...": "no direct identifiers" }
}
```
Topics (TSD §54): `customer-events, matching-events, opportunity-events, institution-events, notification-events, commercial-events, audit-events, integrity-events, workflow-events`.

**Event payloads never carry direct identifiers** (name/phone/NIN). Consumers resolve them through the Disclosure Gateway if permitted.

## 4. Delivery semantics (TSD §55–57)
- **Transactional outbox:** business write + `platform.outbox` insert in one transaction.
- **Dispatcher** (worker): `SELECT … FOR UPDATE SKIP LOCKED LIMIT 100` → for each subscribed consumer → handler. Consumer dedupe via `platform.inbox(consumer, event_id)` inserted in the handler's transaction (exactly-once *effect*).
- **Retry:** per consumer: attempts 5, backoff 1 s, 10 s, 60 s, 5 min, 15 min → dead letter (`platform.dead_letter`) → alert if topic is critical (routing, consent, notification, billing).
- **Replay:** admin can replay a dead letter or re-emit an event range for a consumer. Idempotent handlers guarantee no duplicate opportunities, charges or messages.
- **Bus adapter:** `EventBus` interface with `PostgresOutboxBus` (V1) and `AzureServiceBusBus` (stub + contract tests) for later.

## 5. Key event catalogue

| Topic | Events |
|---|---|
| customer | SessionStarted, NeedCreated, IntentConfirmed, PhoneVerified, FactRecorded, FactConflictDetected, ProfileSnapshotted, ReadinessEvaluated, WaitingRoomOptIn/Expired, CustomerReactivated, NeedClosed |
| matching | NeedReadyForMatching, ClearingRunCompleted, MatchesCreated, MatchesInvalidated, MatchSelected, WaitingRoomMatchFound, SimulationRun |
| institution | InstitutionApplicationSubmitted, InstitutionVerified/Rejected, InstitutionActivated/Paused/Suspended, ProductSubmitted/Approved/Activated/Paused/Archived, AppetiteSimulated/Approved/Activated/Changed/Paused/Expired, CapacityChanged, RoutingRulesChanged |
| opportunity | ConsentGranted/Withdrawn, OpportunityQualified, OpportunityRouted, OpportunityRoutingFailed, OpportunityReceived, OpportunityViewed, OpportunityAssigned, ServiceTargetApproaching/Breached, OpportunityContacted, OutcomeReported, OpportunityWithdrawn, FreshnessChanged, OpportunityClosed, InterestExpressed |
| commercial | CommercialEventCreated, CommercialEventReversed, DisputeOpened, DisputeDecided |
| integrity | IntegritySignalRaised, IntegrityCaseOpened/Decided |
| notification | NotificationQueued/Sent/Failed/Acked/Escalated |
| audit | KillSwitchChanged, ConfigChanged, PrivilegedAccess |

## 6. Observability (TSD §64–67; Skill §61)

- **Correlation ID:** `X-Correlation-ID` accepted/generated at the edge → contextvar → logs, outbox events, AI logs, notification records, error responses.
- **Structured JSON logs** with a redaction filter: keys matching `phone|nin|otp|password|token|name|email|address|document` are masked, and values matching phone/NIN regexes are masked. Unit-tested.
- **Metrics** (`/metrics` Prometheus format, admin-only): HTTP latency/error by route, outbox lag & depth, dead letters, consumer failures, AI latency/tokens/cost/fallback/validation failures, OTP success, matching latency, routing success, notification success, consent completion, opportunities created, billing events.
- **Graph metrics:** per graph & node: entries, completions, drop-off, avg iterations, time-in-node, retries, escalations, human interventions, budget exhaustions. Rendered in admin A-01 and the Graph Inspector.
- **Health:** `/healthz` (liveness), `/readyz` (DB, outbox lag < 60 s, AI mode).
- **Tracing:** OpenTelemetry instrumentation wired (FastAPI, SQLAlchemy, httpx). Exporter is configurable (console in dev, Azure Monitor later).
