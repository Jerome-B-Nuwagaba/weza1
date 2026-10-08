"""Background worker (TSD §62; blueprint 06 L5–L7, 08 §4): outbox dispatch, graph timers, service targets,
freshness, notification retry/escalation, waiting-room expiry, hourly clearing, nightly learning & retention.

Run standalone with `python -m weza.worker`, or in-process inside the API (RUN_WORKER_INPROCESS=true)."""

import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select

import weza.consumers  # noqa: F401 — registers consumers
import weza.domains.need.journey  # noqa: F401 — registers graphs
from weza.config import get_settings
from weza.domains.intelligence import insights
from weza.domains.matching import engine
from weza.domains.matching.models import WaitingEntry
from weza.domains.misc_models import MarketSnapshot
from weza.domains.notification import service as notify
from weza.domains.opportunity import service as opp_svc
from weza.platform.controls import purge_rate_counters
from weza.platform.db import session_scope, utcnow
from weza.platform.events import dispatch_pending
from weza.platform.graph import Trigger, due_timers, resume
from weza.platform.models import EventDelivery

log = logging.getLogger("weza.worker")


def run_graph_timers() -> int:
    n = 0
    with session_scope() as db:
        for inst in due_timers(db):
            try:
                with db.begin_nested():
                    resume(db, inst, Trigger("TIMEOUT", actor="timer"))
                n += 1
            except Exception:  # noqa: BLE001
                inst.attempt_count += 1
                inst.next_action_at = utcnow() + timedelta(minutes=5 * inst.attempt_count)
                if inst.attempt_count >= 5:
                    inst.status = "FAILED"
                    from weza.domains.integrity.service import add_review
                    add_review(db, "GRAPH_FAILED", f"Workflow {inst.graph_type} failed at {inst.current_node}",
                               "graph", inst.id, severity="HIGH")
                log.exception("graph_timer_failed")
    return n


def waiting_room_sweep() -> int:
    now = utcnow()
    n = 0
    with session_scope() as db:
        for w in db.execute(select(WaitingEntry).where(WaitingEntry.status.in_(["OPTED_IN", "RECONFIRM_DUE"]))).scalars():
            if w.expires_at <= now:
                w.status = "EXPIRED"
                notify.notify_customer(db, w.customer_id, "WaitingRoomExpired", title="Waiting Room ended",
                                       body="We didn't find a match within 30 days, so your request has closed. You can "
                                            "start a new one any time.", link="/start")
                n += 1
            elif w.status == "OPTED_IN" and w.reconfirm_due_at <= now:
                w.status = "RECONFIRM_DUE"
                notify.notify_customer(db, w.customer_id, "WaitingRoomReconfirm", title="Still looking?",
                                       body="Your request is still in the WEZA Waiting Room. Do you still need this "
                                            "financing? Open WEZA to keep looking.", link="/c/status")
                n += 1
    return n


def dead_letter_alerts() -> None:
    with session_scope() as db:
        from weza.domains.integrity.service import add_review
        for d in db.execute(select(EventDelivery).where(EventDelivery.status == "DEAD", EventDelivery.critical.is_(True))
                            ).scalars():
            add_review(db, "DEAD_LETTER", f"Critical event failed: {d.consumer}", "event_delivery", d.id,
                       severity="HIGH", detail={"error": (d.last_error or "")[:300]})


def hourly_clearing() -> None:
    with session_scope() as db:
        engine.clear_market(db, "HourlySweep")
        db.add(MarketSnapshot(data=insights.market_state(db)))


def nightly() -> None:
    with session_scope() as db:
        insights.outcome_insights_job(db)
        purge_rate_counters(db)


def _sweep(fn: Callable) -> Callable[[], None]:
    def run():
        with session_scope() as db:
            fn(db)
    return run


JOBS: list[tuple[str, float, Callable[[], object]]] = [
    ("graph_timers", 15, run_graph_timers),
    ("service_targets", 60, _sweep(opp_svc.service_target_sweep)),
    ("freshness", 300, _sweep(opp_svc.freshness_sweep)),
    ("notify_retry", 60, _sweep(notify.retry_sweep)),
    ("notify_escalation", 60, _sweep(notify.escalation_sweep)),
    ("waiting_room", 600, waiting_room_sweep),
    ("dead_letters", 120, dead_letter_alerts),
    ("hourly_clearing", 3600, hourly_clearing),
    ("nightly", 86400, nightly),
]


class Worker:
    def __init__(self, poll: float | None = None):
        self.poll = poll or get_settings().worker_poll_seconds
        self.last: dict[str, float] = {name: time.monotonic() for name, *_ in JOBS}
        self.last["graph_timers"] = 0
        self._stop = threading.Event()

    def tick(self) -> None:
        try:
            dispatch_pending(200)
        except Exception:  # noqa: BLE001
            log.exception("dispatch_failed")
        now = time.monotonic()
        for name, every, fn in JOBS:
            if now - self.last[name] >= every:
                self.last[name] = now
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    log.exception("job_failed", extra={"data": {"job": name}})

    def run_forever(self) -> None:
        log.info("worker_started")
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.poll)

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name="weza-worker", daemon=True)
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()


if __name__ == "__main__":
    from weza.platform.logging import configure_logging
    configure_logging()
    Worker().run_forever()
