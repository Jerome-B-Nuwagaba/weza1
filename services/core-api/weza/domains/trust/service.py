"""Audit and decision-ledger writers. These are the only way other domains record governance history."""

from typing import Any

from sqlalchemy.orm import Session

from weza.domains.trust.models import AuditEvent, Decision
from weza.platform.context import Actor, correlation_id


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    import json
    return json.loads(json.dumps(v, default=str))


def audit(db: Session, actor: Actor, action: str, object_type: str, object_id, *, before: dict | None = None,
          after: dict | None = None, reason: str | None = None, institution_id=None,
          versions: dict | None = None) -> AuditEvent:
    ev = AuditEvent(
        actor_type=actor.kind, actor_id=str(actor.id) if actor.id else None, actor_display=actor.display[:120],
        institution_id=institution_id if institution_id is not None else actor.institution_id,
        action=action, object_type=object_type, object_id=str(object_id), before=_jsonable(before),
        after=_jsonable(after), reason=reason, versions=_jsonable(versions), correlation_id=correlation_id(),
        ip=actor.ip or None,
    )
    db.add(ev)
    return ev


def record_decision(db: Session, decision_type: str, subject_type: str, subject_id, *, inputs: dict, output: dict,
                    explanation: dict | None = None, ruleset_version: str | None = None,
                    algorithm_version: str | None = None, model_version: str | None = None) -> Decision:
    d = Decision(decision_type=decision_type, subject_type=subject_type, subject_id=str(subject_id),
                 input_snapshot=_jsonable(inputs), output=_jsonable(output), explanation=_jsonable(explanation or {}),
                 ruleset_version=ruleset_version, algorithm_version=algorithm_version, model_version=model_version)
    db.add(d)
    return d
