"""Retry and dead-letter handling for staff notification delivery (resiliency spec §8).

FAILED rows carry next_attempt_at with exponential backoff; the worker's retry sweep picks them up when due. After
MAX_ATTEMPTS a row is DEAD (the dead-letter state) and can be replayed from the admin console. Failures never raise
into the business transaction that created the notification."""

import logging
from datetime import timedelta

from weza.platform.db import utcnow

log = logging.getLogger("weza.notify.retry")

MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [60, 300, 900, 3600]  # after failed attempts 1–4; the 5th failure dead-letters


def backoff_for(attempts: int) -> timedelta:
    return timedelta(seconds=BACKOFF_SECONDS[min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1])


def record_failure(note, exc: Exception) -> None:
    note.last_error = str(exc)[:500]
    if note.attempts >= MAX_ATTEMPTS:
        note.status, note.next_attempt_at = "DEAD", None
        log.error("notification_dead_lettered", extra={"data": {"notification": str(note.id)}})
        return
    note.status, note.next_attempt_at = "FAILED", utcnow() + backoff_for(note.attempts)


def requeue(note) -> None:
    """Admin replay of a dead-lettered notification: a fresh set of attempts, starting now."""
    note.status, note.attempts, note.next_attempt_at = "FAILED", 0, utcnow()
