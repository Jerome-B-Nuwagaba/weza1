"""WEZA graph runtime (blueprint 08 §1).

A small, typed, persisted workflow engine: nodes are plain functions, state lives in Postgres, waiting
nodes always carry a timeout, transitions are recorded, and every change commits atomically with the
domain writes and outbox events of the same request.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.platform.db import utcnow
from weza.platform.errors import Conflict
from weza.platform.events import emit
from weza.platform.models import GraphInstance, GraphTransition

MAX_STEPS_PER_ADVANCE = 40


@dataclass
class Wait:
    kind: str  # CUSTOMER_REPLY | OTP | CONSENT | HUMAN_APPROVAL | INSTITUTION_ACTION | TIMER
    timeout_s: int | None = None


@dataclass
class Step:
    to: str | None = None  # next node; None = stay on current node
    patch: dict[str, Any] = field(default_factory=dict)
    wait: Wait | None = None
    terminal: str | None = None  # COMPLETED | EXPIRED | CANCELLED | FAILED


@dataclass
class Trigger:
    kind: str  # ENTER | CUSTOMER_REPLY | OTP | TIMEOUT | ...
    payload: dict[str, Any] = field(default_factory=dict)
    actor: str = "system"


NodeFn = Callable[["Ctx", dict, Trigger], Step]


@dataclass
class Node:
    fn: NodeFn
    autonomy: int = 2  # Skill §60
    on_timeout: str | None = None  # node to go to when a wait on this node times out


@dataclass
class GraphDef:
    type: str
    version: int
    start: str
    nodes: dict[str, Node]


@dataclass
class Ctx:
    db: Session
    instance: GraphInstance
    outputs: list[dict] = field(default_factory=list)  # messages/cards produced during this advance

    def say(self, text: str, **extra) -> None:
        self.outputs.append({"type": "text", "text": text, **extra})

    def card(self, kind: str, data: dict) -> None:
        self.outputs.append({"type": "card", "card": kind, "data": data})


_graphs: dict[tuple[str, int], GraphDef] = {}


def register(g: GraphDef) -> GraphDef:
    _graphs[(g.type, g.version)] = g
    return g


def start(db: Session, graph: GraphDef, state: dict, **refs) -> tuple[GraphInstance, list[dict]]:
    inst = GraphInstance(graph_type=graph.type, graph_version=graph.version, current_node=graph.start,
                         state=state, status="RUNNING", **refs)
    db.add(inst)
    db.flush()
    outputs = _advance(db, inst, Trigger("ENTER"))
    return inst, outputs


def load_for_update(db: Session, instance_id: uuid.UUID) -> GraphInstance:
    inst = db.execute(select(GraphInstance).where(GraphInstance.id == instance_id).with_for_update()).scalar_one_or_none()
    if inst is None:
        raise Conflict("Workflow not found.", code="GRAPH_NOT_FOUND", status=404)
    return inst


def resume(db: Session, inst: GraphInstance, trigger: Trigger) -> list[dict]:
    if inst.status in ("COMPLETED", "EXPIRED", "CANCELLED", "FAILED"):
        raise Conflict("This journey has ended.", code="GRAPH_ENDED")
    if trigger.kind != "TIMEOUT" and inst.waiting_for and trigger.kind != inst.waiting_for and \
            not trigger.payload.get("_any"):
        raise Conflict(f"Expected {inst.waiting_for}, got {trigger.kind}.", code="UNEXPECTED_INPUT")
    return _advance(db, inst, trigger)


def _advance(db: Session, inst: GraphInstance, trigger: Trigger) -> list[dict]:
    g = _graphs[(inst.graph_type, inst.graph_version)]
    ctx = Ctx(db=db, instance=inst)
    current_trigger = trigger
    for _ in range(MAX_STEPS_PER_ADVANCE):
        node = g.nodes[inst.current_node]
        if current_trigger.kind == "TIMEOUT" and node.on_timeout:
            step = Step(to=node.on_timeout)
        else:
            step = node.fn(ctx, inst.state, current_trigger)
        if step.patch:
            inst.state = {**inst.state, **step.patch}
        if step.to and step.to != inst.current_node:
            db.add(GraphTransition(instance_id=inst.id, from_node=inst.current_node, to_node=step.to,
                                   trigger=current_trigger.kind, autonomy_level=g.nodes[step.to].autonomy,
                                   actor=current_trigger.actor))
            emit(db, "GraphTransitioned", topic="workflow", aggregate_type="graph", aggregate_id=inst.id,
                 data={"graph_type": inst.graph_type, "from": inst.current_node, "to": step.to,
                       "trigger": current_trigger.kind})
            inst.current_node = step.to
        if step.terminal:
            inst.status = step.terminal
            inst.waiting_for = None
            inst.next_action_at = None
            break
        if step.wait:
            inst.state = {**inst.state, "_wait_node": inst.current_node}
            inst.status = "WAITING"
            inst.waiting_for = step.wait.kind
            inst.next_action_at = (utcnow() + timedelta(seconds=step.wait.timeout_s)) if step.wait.timeout_s else None
            break
        if not step.to:
            # A node that neither moves, waits nor terminates would loop forever — treat as a defect.
            inst.status = "FAILED"
            inst.error_state = {"reason": "node_stalled", "node": inst.current_node}
            break
        inst.status = "RUNNING"
        current_trigger = Trigger("ENTER", actor=current_trigger.actor)
    else:
        inst.status = "FAILED"
        inst.error_state = {"reason": "step_budget_exhausted", "node": inst.current_node}
    inst.version += 1
    inst.updated_at = utcnow()
    db.flush()
    return ctx.outputs


def due_timers(db: Session, limit: int = 50) -> list[GraphInstance]:
    return list(db.execute(
        select(GraphInstance)
        .where(GraphInstance.status == "WAITING", GraphInstance.next_action_at.is_not(None),
               GraphInstance.next_action_at <= utcnow())
        .limit(limit).with_for_update(skip_locked=True)
    ).scalars())
