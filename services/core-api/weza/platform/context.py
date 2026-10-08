"""Request-scoped context: correlation ID (TSD §65) and the authenticated actor."""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def correlation_id() -> str:
    cid = correlation_id_var.get()
    if not cid:
        cid = uuid.uuid4().hex
        correlation_id_var.set(cid)
    return cid


@dataclass(frozen=True)
class Actor:
    """Who is acting. Tenant context comes ONLY from authenticated identity (TSD §47)."""

    kind: str  # CUSTOMER | INSTITUTION_USER | WEZA_USER | SYSTEM | ANONYMOUS
    id: uuid.UUID | None = None
    institution_id: uuid.UUID | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    team_id: uuid.UUID | None = None
    mfa: bool = False
    display: str = ""

    @property
    def is_weza(self) -> bool:
        return self.kind == "WEZA_USER"

    @property
    def is_institution(self) -> bool:
        return self.kind == "INSTITUTION_USER"


SYSTEM = Actor(kind="SYSTEM", display="system")
