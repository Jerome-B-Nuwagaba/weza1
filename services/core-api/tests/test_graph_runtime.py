"""Graph runtime (Skill §62): nodes, edges, waits, interrupts, invalid input, timeouts, terminals, budgets."""

import pytest

from weza.platform.db import session_scope, utcnow
from weza.platform.errors import Conflict
from weza.platform.graph import GraphDef, Node, Step, Trigger, Wait, due_timers, register, resume, start


def _a(ctx, st, t):
    if t.kind == "ENTER":
        ctx.say("question")
        return Step(wait=Wait("CUSTOMER_REPLY", 60))
    return Step(to="B", patch={"answer": t.payload.get("text")})


def _b(ctx, st, t):
    return Step(terminal="COMPLETED")


def _timeout(ctx, st, t):
    return Step(terminal="EXPIRED", patch={"timed_out": True})


def _loop(ctx, st, t):
    return Step(to="L2")


def _loop2(ctx, st, t):
    return Step(to="L1")


G = register(GraphDef("test_graph", 1, "A", {"A": Node(_a, 0, "T"), "B": Node(_b), "T": Node(_timeout)}))
LOOP = register(GraphDef("test_loop", 1, "L1", {"L1": Node(_loop), "L2": Node(_loop2)}))


def test_wait_resume_and_complete():
    with session_scope() as db:
        inst, out = start(db, G, {})
        assert inst.status == "WAITING" and inst.waiting_for == "CUSTOMER_REPLY" and out[0]["text"] == "question"
        assert inst.next_action_at is not None
        resume(db, inst, Trigger("CUSTOMER_REPLY", {"text": "hi"}))
        assert inst.status == "COMPLETED" and inst.state["answer"] == "hi" and inst.current_node == "B"


def test_unexpected_interrupt_is_rejected():
    with session_scope() as db:
        inst, _ = start(db, G, {})
        with pytest.raises(Conflict):
            resume(db, inst, Trigger("OTP", {}))


def test_timeout_path_never_hangs():
    with session_scope() as db:
        inst, _ = start(db, G, {})
        inst.next_action_at = utcnow()
        iid = inst.id
    with session_scope() as db:
        due = [i for i in due_timers(db, 500) if i.id == iid]
        assert due
        resume(db, due[0], Trigger("TIMEOUT"))
        assert due[0].status == "EXPIRED" and due[0].state["timed_out"] is True


def test_ended_graph_rejects_input():
    with session_scope() as db:
        inst, _ = start(db, G, {})
        resume(db, inst, Trigger("CUSTOMER_REPLY", {"text": "x"}))
        with pytest.raises(Conflict):
            resume(db, inst, Trigger("CUSTOMER_REPLY", {"text": "again"}))


def test_unbounded_loop_is_stopped_by_step_budget():
    with session_scope() as db:
        inst, _ = start(db, LOOP, {})
        assert inst.status == "FAILED" and inst.error_state["reason"] == "step_budget_exhausted"
