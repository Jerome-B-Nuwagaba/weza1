"""Event bus: transactional outbox + consumer registry + dispatcher with retry, dead-letter and replay
(TSD §54–57; blueprint 08 §3–4).

Producers call `emit()` inside their business transaction. The dispatcher (worker) delivers each event to
every subscribed consumer in its own transaction. Handlers must be idempotent; the (event, consumer)
delivery row makes re-delivery a no-op once DONE.
"""

import logging
import traceback
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.platform.context import correlation_id
from weza.platform.db import SessionLocal, utcnow
from weza.platform.models import EventDelivery, OutboxEvent

log = logging.getLogger("weza.events")

BACKOFF_SECONDS = [1, 10, 60, 300, 900]
MAX_ATTEMPTS = len(BACKOFF_SECONDS)

TOPICS = {
    "customer", "matching", "institution", "opportunity", "commercial", "integrity", "notification",
    "audit", "workflow",
}


@dataclass
class Consumer:
    name: str
    events: set[str]
    handler: Callable[[Session, OutboxEvent], None]
    critical: bool = False


_registry: dict[str, list[Consumer]] = defaultdict(list)
_by_name: dict[str, Consumer] = {}


def consumer(name: str, events: list[str], critical: bool = False):
    def deco(fn: Callable[[Session, OutboxEvent], None]):
        c = Consumer(name=name, events=set(events), handler=fn, critical=critical)
        _by_name[name] = c
        for e in events:
            _registry[e].append(c)
        return fn
    return deco


def emit(db: Session, event_type: str, *, topic: str, aggregate_type: str, aggregate_id, data: dict | None = None,
         institution_id: uuid.UUID | None = None, synthetic: bool = False) -> OutboxEvent:
    assert topic in TOPICS, topic
    ev = OutboxEvent(
        event_type=event_type, topic=topic, aggregate_type=aggregate_type, aggregate_id=str(aggregate_id),
        institution_id=institution_id, correlation_id=correlation_id(), data=data or {}, synthetic=synthetic,
    )
    db.add(ev)
    db.flush()
    for c in _registry.get(event_type, []):
        db.add(EventDelivery(event_id=ev.id, consumer=c.name, critical=c.critical))
    return ev


def dispatch_pending(limit: int = 100) -> int:
    """Deliver due events. Safe to run concurrently in several workers (SKIP LOCKED)."""
    processed = 0
    while processed < limit:
        db = SessionLocal()
        try:
            row = db.execute(
                select(EventDelivery)
                .where(EventDelivery.status == "PENDING", EventDelivery.next_attempt_at <= utcnow())
                .order_by(EventDelivery.next_attempt_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if row is None:
                db.rollback()
                return processed
            event = db.get(OutboxEvent, row.event_id)
            c = _by_name.get(row.consumer)
            try:
                if c is not None and event is not None:
                    with db.begin_nested():
                        c.handler(db, event)
                row.status = "DONE"
                row.completed_at = utcnow()
                row.attempts += 1
            except Exception as exc:  # noqa: BLE001 — any handler failure is retried then dead-lettered
                row.attempts += 1
                row.last_error = "".join(traceback.format_exception_only(type(exc), exc))[:2000]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "DEAD"
                    log.error("event_dead_lettered", extra={"data": {
                        "consumer": row.consumer, "event_type": event.event_type if event else None,
                        "critical": row.critical}})
                else:
                    row.next_attempt_at = utcnow() + timedelta(seconds=BACKOFF_SECONDS[row.attempts - 1])
                    log.warning("event_retry_scheduled", extra={"data": {"consumer": row.consumer,
                                                                         "attempts": row.attempts}})
            db.commit()
            processed += 1
        finally:
            db.close()
    return processed


def drain(max_rounds: int = 50) -> None:
    """Deliver everything that is due now, repeatedly (events can emit events). Used by tests/seed."""
    for _ in range(max_rounds):
        if dispatch_pending() == 0:
            return


def replay_delivery(db: Session, delivery_id: uuid.UUID) -> None:
    row = db.get(EventDelivery, delivery_id)
    if row is None:
        return
    row.status = "PENDING"
    row.attempts = 0
    row.next_attempt_at = utcnow()
    row.last_error = None
