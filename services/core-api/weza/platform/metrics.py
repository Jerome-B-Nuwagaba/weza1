"""Operational metrics (TSD §64-65), exposed in the Prometheus text format at /metrics.

Two kinds:
- in-process timers and counters (HTTP requests by route and status, matching duration), kept per worker process; and
- gauges read from the database on each scrape (queue depth, ages, failures, business activity in the last 24 hours).
Nothing here carries personal data: labels are route templates, status classes, job and state names.
/metrics is off unless METRICS_TOKEN is set, and then needs `Authorization: Bearer <token>`.
"""

import functools
import logging
import threading
import time
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from weza.platform.db import utcnow

log = logging.getLogger("weza.metrics")

BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_lock = threading.Lock()
_counts: dict[tuple, int] = defaultdict(int)  # (metric, labels...) -> n
_hist: dict[tuple, list[float]] = {}  # (metric, labels...) -> [bucket counts..., +Inf, sum]


def observe(metric: str, seconds: float, *labels: str) -> None:
    """Record one duration in a histogram (and its count)."""
    with _lock:
        row = _hist.setdefault((metric, *labels), [0.0] * (len(BUCKETS) + 2))
        for i, upper in enumerate(BUCKETS):
            if seconds <= upper:
                row[i] += 1
        row[len(BUCKETS)] += 1  # +Inf bucket == total count
        row[len(BUCKETS) + 1] += seconds


def count(metric: str, *labels: str) -> None:
    with _lock:
        _counts[(metric, *labels)] += 1


def timed(metric: str):
    """Decorator: time a function into the histogram `metric`."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            started = time.monotonic()
            try:
                return fn(*a, **k)
            finally:
                observe(metric, time.monotonic() - started)
        return inner
    return wrap


def reset() -> None:  # tests
    with _lock:
        _counts.clear()
        _hist.clear()


def _labels(names: tuple[str, ...], values: tuple) -> str:
    return "{" + ",".join(f'{n}="{str(v)}"' for n, v in zip(names, values, strict=False)) + "}" if names else ""


def _histogram_lines(metric: str, help_text: str, label_names: tuple[str, ...]) -> list[str]:
    out = [f"# HELP {metric} {help_text}", f"# TYPE {metric} histogram"]
    with _lock:
        rows = {k[1:]: list(v) for k, v in _hist.items() if k[0] == metric}
    for labels, row in sorted(rows.items()):
        base = _labels(label_names, labels)[1:-1]
        join = (base + ",") if base else ""
        for i, upper in enumerate(BUCKETS):
            out.append(f'{metric}_bucket{{{join}le="{upper}"}} {int(row[i])}')
        out.append(f'{metric}_bucket{{{join}le="+Inf"}} {int(row[len(BUCKETS)])}')
        out.append(f"{metric}_sum{_labels(label_names, labels)} {row[len(BUCKETS) + 1]:.6f}")
        out.append(f"{metric}_count{_labels(label_names, labels)} {int(row[len(BUCKETS)])}")
    return out


def _gauge(out: list[str], name: str, help_text: str, samples: list[tuple[dict, float | int | None]]) -> None:
    out += [f"# HELP {name} {help_text}", f"# TYPE {name} gauge"]
    for labels, value in samples:
        if value is None:
            continue
        lab = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}" if labels else ""
        out.append(f"{name}{lab} {value}")


def _age(db: Session, query) -> float | None:
    oldest = db.execute(query).scalar_one_or_none()
    return round((utcnow() - oldest).total_seconds(), 1) if oldest else 0.0


def database_gauges(db: Session) -> list[str]:
    """Queue depth, ages, failures and business activity, read from the database at scrape time."""
    from weza.domains.consent.models import Consent
    from weza.domains.misc_models import AiCallLog, Notification, WhatsappInbox
    from weza.domains.opportunity.models import Opportunity
    from weza.platform.models import EventDelivery, GraphInstance
    now, day, hour = utcnow(), utcnow() - timedelta(hours=24), utcnow() - timedelta(hours=1)
    out: list[str] = []
    deliveries = dict(db.execute(select(EventDelivery.status, func.count()).group_by(EventDelivery.status)).all())
    _gauge(out, "weza_outbox_deliveries", "Event deliveries by status (queue depth: PENDING; failures: DEAD).",
           [({"status": s}, deliveries.get(s, 0)) for s in ("PENDING", "DEAD", "DONE")])
    _gauge(out, "weza_outbox_oldest_pending_seconds", "Age of the oldest undelivered event.",
           [({}, _age(db, select(func.min(EventDelivery.next_attempt_at)).where(EventDelivery.status == "PENDING")))])
    _gauge(out, "weza_whatsapp_inbox_pending", "Inbound WhatsApp messages waiting to be processed.",
           [({}, db.execute(select(func.count()).select_from(WhatsappInbox).where(WhatsappInbox.status == "PENDING")).scalar_one())])
    _gauge(out, "weza_whatsapp_inbox_oldest_pending_seconds", "Age of the oldest unprocessed WhatsApp message.",
           [({}, _age(db, select(func.min(WhatsappInbox.received_at)).where(WhatsappInbox.status == "PENDING")))])
    _gauge(out, "weza_journeys_overdue", "Conversations whose timer has passed and not yet been advanced.",
           [({}, db.execute(select(func.count()).select_from(GraphInstance).where(
               GraphInstance.status == "WAITING", GraphInstance.next_action_at < now)).scalar_one())])
    notes = dict(db.execute(select(Notification.status, func.count()).where(Notification.created_at >= day)
                            .group_by(Notification.status)).all())
    sent = sum(notes.get(s, 0) for s in ("SENT", "DELIVERED", "READ", "ACKED"))
    failed = sum(notes.get(s, 0) for s in ("FAILED", "DEAD"))
    _gauge(out, "weza_notifications_24h", "Notifications in the last 24 hours by outcome.",
           [({"outcome": "ok"}, sent), ({"outcome": "failed"}, failed)])
    ai = db.execute(select(func.count(), func.count().filter(AiCallLog.fallback_used),
                           func.count().filter(AiCallLog.validation_ok.is_(False)),
                           func.count().filter(AiCallLog.error.is_not(None)),
                           func.coalesce(func.sum(AiCallLog.cost_usd), 0)).where(AiCallLog.created_at >= hour)).one()
    _gauge(out, "weza_ai_calls_1h", "AI capability calls in the last hour by result.",
           [({"result": "total"}, ai[0]), ({"result": "fallback"}, ai[1]), ({"result": "validation_failed"}, ai[2]),
            ({"result": "error"}, ai[3])])
    _gauge(out, "weza_ai_cost_usd_1h", "Estimated AI spend in the last hour (USD).", [({}, float(ai[4]))])
    opps = dict(db.execute(select(Opportunity.state, func.count()).where(Opportunity.qualified_at >= day)
                           .group_by(Opportunity.state)).all())
    _gauge(out, "weza_opportunities_24h", "Opportunities created in the last 24 hours by state "
           "(routing success = anything but ROUTING_FAILED).", [({"state": s}, n) for s, n in sorted(opps.items())])
    _gauge(out, "weza_consents_granted_24h", "Customer consents granted in the last 24 hours.",
           [({}, db.execute(select(func.count()).select_from(Consent).where(Consent.granted_at >= day)).scalar_one())])
    try:
        from weza.domains.commercial.models import CommercialEvent
        billed = db.execute(select(func.count()).select_from(CommercialEvent).where(CommercialEvent.created_at >= day)).scalar_one()
        _gauge(out, "weza_commercial_events_24h", "Billing events recorded in the last 24 hours.", [({}, billed)])
    except Exception:  # noqa: BLE001 — a metric must never break the scrape
        log.warning("metrics_commercial_events_unavailable")
    return out


def dependency_gauges(db: Session | None) -> list[str]:
    from weza.config import get_settings
    s = get_settings()
    up = 1
    if db is not None:
        try:
            db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            up = 0
    out: list[str] = []
    _gauge(out, "weza_dependency_up", "1 when the dependency answers or is configured, 0 when it is not.",
           [({"dependency": "database"}, up), ({"dependency": "whatsapp_configured"}, int(s.whatsapp_send_ready)),
            ({"dependency": "crb_configured"}, int(not s.crb_missing)),
            ({"dependency": "ai_configured"}, int(bool(s.anthropic_api_key)))])
    return out


def render(db: Session | None) -> str:
    """The whole exposition: this process's timers, then the database gauges."""
    out = _histogram_lines("weza_http_request_seconds", "HTTP request duration by route and status class.",
                           ("method", "route", "status"))
    out += _histogram_lines("weza_matching_seconds", "Time to match one need against every active mandate.", ())
    with _lock:
        counters = sorted((k, v) for k, v in _counts.items())
    out += ["# HELP weza_events_total Counted events (name, outcome).", "# TYPE weza_events_total counter"]
    out += [f'weza_events_total{{name="{k[0]}",outcome="{k[1] if len(k) > 1 else ""}"}} {v}' for k, v in counters]
    out += dependency_gauges(db)
    if db is not None:
        try:
            out += database_gauges(db)
        except Exception:  # noqa: BLE001 — still answer, with what we have
            out += ["# database gauges unavailable"]
    return "\n".join(out) + "\n"
