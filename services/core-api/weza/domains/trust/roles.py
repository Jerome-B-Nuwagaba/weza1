"""Canonical WEZA V1 role vocabulary.

The product specification names five roles: WEZA_ADMIN, INSTITUTION_ADMIN, INSTITUTION_MANAGER,
INSTITUTION_OFFICER and COMPLIANCE_VIEWER. The permission model (`weza.domains.trust.policy`) is
the enforcement point and already ships a working vocabulary (INST_ADMIN, MANAGER, OFFICER,
COMPLIANCE, WEZA_SUPER, ...). This module bridges the two so both spellings work and nothing that
already exists has to be renamed.

`expand()` is applied to every authenticated actor (see `weza.domains.identity.service`), so a
membership holding "OFFICER" yields an actor whose role set contains both OFFICER and
INSTITUTION_OFFICER, and a membership holding "INSTITUTION_OFFICER" yields both. Role checks in
either vocabulary therefore hold, and `identity.membership.roles` keeps storing whatever the
institution's administrator chose.

Institution roles outside the canonical five (EXECUTIVE, BUSINESS, CREDIT_RISK) are working
roles with no canonical equivalent; they are not mapped and keep their own permissions.
"""

from collections.abc import Iterable

from weza.platform.context import Actor
from weza.platform.errors import Forbidden

WEZA_ADMIN = "WEZA_ADMIN"
INSTITUTION_ADMIN = "INSTITUTION_ADMIN"
INSTITUTION_MANAGER = "INSTITUTION_MANAGER"
INSTITUTION_OFFICER = "INSTITUTION_OFFICER"
COMPLIANCE_VIEWER = "COMPLIANCE_VIEWER"

CANONICAL_ROLES: list[str] = [WEZA_ADMIN, INSTITUTION_ADMIN, INSTITUTION_MANAGER, INSTITUTION_OFFICER,
                               COMPLIANCE_VIEWER]

#: Canonical role -> every concrete role string that satisfies it.
ROLE_MEMBERSHIP: dict[str, frozenset[str]] = {
    WEZA_ADMIN: frozenset({"WEZA_ADMIN", "WEZA_SUPER"}),
    INSTITUTION_ADMIN: frozenset({"INSTITUTION_ADMIN", "INST_ADMIN"}),
    INSTITUTION_MANAGER: frozenset({"INSTITUTION_MANAGER", "MANAGER"}),
    INSTITUTION_OFFICER: frozenset({"INSTITUTION_OFFICER", "OFFICER"}),
    COMPLIANCE_VIEWER: frozenset({"COMPLIANCE_VIEWER", "COMPLIANCE"}),
}

#: Concrete role string -> the canonical role it satisfies (if any).
ROLE_TO_CANONICAL: dict[str, str] = {
    role: canonical for canonical, members in ROLE_MEMBERSHIP.items() for role in members
}

CANONICAL_LABELS: dict[str, str] = {
    WEZA_ADMIN: "WEZA administrator",
    INSTITUTION_ADMIN: "Institution administrator",
    INSTITUTION_MANAGER: "Institution manager",
    INSTITUTION_OFFICER: "Institution officer",
    COMPLIANCE_VIEWER: "Compliance viewer",
}


def expand(roles: Iterable[str] | frozenset[str] | set[str] | None) -> frozenset[str]:
    """Expand a role set so it holds both vocabularies.

    A working role ("OFFICER") also satisfies the canonical role that stands for it
    ("INSTITUTION_OFFICER"), and a canonical role held directly also satisfies the working role it
    stands for. Every check in either vocabulary therefore holds, whichever spelling was granted.
    Order-independent and idempotent.
    """
    out = set(roles or ())
    for role in list(out):
        canonical = ROLE_TO_CANONICAL.get(role)
        if canonical:
            out.add(canonical)
    for role in list(out):
        members = ROLE_MEMBERSHIP.get(role)
        if members:
            out |= set(members)
    return frozenset(out)


def spellings(canonical: str) -> list[str]:
    """Every concrete role string that satisfies the canonical role, including the canonical name."""
    if canonical not in ROLE_MEMBERSHIP:
        raise ValueError(f"Unknown canonical role: {canonical}")
    return sorted(ROLE_MEMBERSHIP[canonical])


def sql_any(column, canonical: str):
    """A SQL predicate matching a stored role array against any spelling of a canonical role.

    Used where the roles live in the database rather than on the actor, so a membership that stores
    "INSTITUTION_OFFICER" is found by a query that looks for officers.
    """
    from sqlalchemy import or_

    return or_(*[column.contains([s]) for s in spellings(canonical)])


def canonical_roles(roles: Iterable[str] | frozenset[str] | set[str] | None) -> frozenset[str]:
    """Only the canonical roles present in the given role set."""
    expanded = expand(roles)
    return frozenset(r for r in CANONICAL_ROLES if r in expanded)


def has_role(actor: Actor, canonical: str) -> bool:
    """True when the actor holds the canonical role (or a working role that satisfies it)."""
    if canonical not in ROLE_MEMBERSHIP:
        raise ValueError(f"Unknown canonical role: {canonical}")
    return bool(actor.roles & ROLE_MEMBERSHIP[canonical])


def require_role(actor: Actor, canonical: str) -> None:
    """Enforce a canonical role. 403 with the role named, so the API contract is explicit."""
    if not has_role(actor, canonical):
        raise Forbidden("You don't have access to this — ask your administrator.", code="ROLE_REQUIRED",
                        details=[{"role": canonical}])
