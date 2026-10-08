"""Rate limiting, idempotency, feature flags, kill switches and server-enforced state machines."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from weza.platform.crypto import sha256_hex
from weza.platform.db import utcnow
from weza.platform.errors import InvalidTransition, RateLimited, ValidationFailed
from weza.platform.models import FeatureFlag, IdempotencyKey, KillSwitch

# ---------------------------------------------------------------- rate limiting (TSD §63)


def rate_limit(db: Session, bucket: str, limit: int, window_seconds: int, message: str | None = None) -> None:
    now = utcnow()
    window_start = datetime.fromtimestamp(int(now.timestamp()) // window_seconds * window_seconds, tz=now.tzinfo)
    count = db.execute(text(
        "INSERT INTO platform.rate_counter(bucket, window_start, count) VALUES (:b, :w, 1) "
        "ON CONFLICT (bucket, window_start) DO UPDATE SET count = platform.rate_counter.count + 1 RETURNING count"
    ), {"b": bucket, "w": window_start}).scalar_one()
    if count > limit:
        raise RateLimited(message or "Too many attempts. Please wait a moment and try again.")


def purge_rate_counters(db: Session) -> None:
    db.execute(text("DELETE FROM platform.rate_counter WHERE window_start < :t"),
               {"t": utcnow() - timedelta(days=1)})


# ---------------------------------------------------------------- idempotency (TSD §60)


def idempotent(db: Session, key: str | None, scope: str, body: dict, fn: Callable[[], dict]) -> dict:
    """Run fn once per (key, scope). Same key + same body → stored response. Same key + other body → 422."""
    if not key:
        raise ValidationFailed("Idempotency-Key header is required for this operation.", code="IDEMPOTENCY_KEY_REQUIRED")
    if len(key) > 200:
        raise ValidationFailed("Idempotency-Key is too long.")
    req_hash = sha256_hex(json.dumps(body, sort_keys=True, default=str))
    existing = db.get(IdempotencyKey, (key, scope))
    if existing:
        if existing.request_hash != req_hash:
            raise ValidationFailed("This Idempotency-Key was already used with a different request.",
                                   code="IDEMPOTENCY_KEY_REUSED")
        return existing.response
    result = fn()
    db.add(IdempotencyKey(key=key, scope=scope, request_hash=req_hash, response=json.loads(json.dumps(result, default=str))))
    db.flush()
    return result


# ---------------------------------------------------------------- flags & kill switches


def flag(db: Session, key: str, default: bool = False) -> bool:
    row = db.get(FeatureFlag, key)
    return row.enabled if row else default


def switch(db: Session, key: str) -> dict:
    row = db.get(KillSwitch, key)
    return row.value if row else {}


def routing_paused(db: Session) -> bool:
    return bool(switch(db, "pause_all_routing").get("on"))


def billing_paused(db: Session) -> bool:
    return bool(switch(db, "pause_billing_events").get("on"))


def channel_disabled(db: Session, channel: str) -> bool:
    return channel in (switch(db, "disabled_channels").get("channels") or [])


def ai_mode(db: Session) -> str:
    return switch(db, "ai_mode").get("mode", "AVAILABLE")


# ---------------------------------------------------------------- state machines (TSD §31)


class StateMachine:
    def __init__(self, name: str, transitions: dict[str, set[str]]):
        self.name = name
        self.transitions = transitions

    def can(self, src: str, dst: str) -> bool:
        return dst in self.transitions.get(src, set())

    def check(self, src: str, dst: str) -> None:
        if not self.can(src, dst):
            raise InvalidTransition(f"{self.name} cannot move from {src} to {dst}.",
                                    details=[{"from": src, "to": dst}])
