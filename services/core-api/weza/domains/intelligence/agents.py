"""Bounded agent supervisor for WEZA.

Agents are orchestration shells around approved capabilities/tools. They never receive DB write authority for
credit, consent, CRB, matching/routing or activation decisions. Every step is allow-listed, bounded and logged
without raw prompts, PII or results.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

from sqlalchemy.orm import Session

from weza.domains.intelligence import ai
from weza.domains.misc_models import AgentStep, LoopMetric
from weza.platform import crypto
from weza.platform.context import correlation_id

T = TypeVar("T")


class AgentPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    tools: frozenset[str]
    max_steps: int


CUSTOMER_CONVERSATION = AgentSpec(
    "customer_conversation",
    frozenset({"extract_financial_intent", "extract_profile_facts", "phrase_next_question"}),
    4,
)
DOCUMENT_EXTRACTION = AgentSpec(
    "document_extraction",
    frozenset({"classify_document", "extract_product_rules"}),
    3,
)
PRODUCT_CONFIGURATION = AgentSpec(
    "product_configuration",
    frozenset({"extract_product_rules", "product.create_draft"}),
    3,
)
INSTITUTION_ASSISTANT = AgentSpec(
    "institution_assistant",
    frozenset({
        "search_opportunities", "get_demand_summary", "get_product_performance",
        "get_near_match_analysis", "simulate_appetite", "get_team_queue",
    }),
    3,
)
MARKETPLACE_INTELLIGENCE = AgentSpec(
    "marketplace_intelligence",
    frozenset({"narrate_insight", "narrate_briefing"}),
    2,
)

AGENTS = {
    x.name: x for x in (
        CUSTOMER_CONVERSATION,
        DOCUMENT_EXTRACTION,
        PRODUCT_CONFIGURATION,
        INSTITUTION_ASSISTANT,
        MARKETPLACE_INTELLIGENCE,
    )
}

# Explicit deny-list: even a future accidental allow-list edit must not grant these through the supervisor.
FORBIDDEN_TOOL_PREFIXES = (
    "credit.approve", "credit.decline", "credit.disburse", "consent.", "crb.",
    "matching.", "routing.", "appetite.activate", "product.approve", "product.activate",
)


def _hash_args(args: dict[str, Any] | None) -> str:
    # Hash only; never persist raw agent/tool args because they may contain customer data.
    blob = json.dumps(args or {}, sort_keys=True, default=str, separators=(",", ":"))
    return crypto.sha256_hex(blob)


def _check(spec: AgentSpec, tool: str, step_no: int) -> None:
    if any(tool.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES):
        raise AgentPolicyError(f"{tool} is outside agent authority")
    if tool not in spec.tools:
        raise AgentPolicyError(f"{tool} is not allowed for {spec.name}")
    if step_no < 1 or step_no > spec.max_steps:
        raise AgentPolicyError(f"{spec.name} step budget exhausted")


def run_step(
    db: Session,
    spec: AgentSpec,
    tool: str,
    args: dict[str, Any] | None,
    fn: Callable[[], T],
    *,
    subject: str | None = None,
    step_no: int = 1,
) -> T:
    """Run one approved agent step and persist safe telemetry whether it succeeds or fails."""
    _check(spec, tool, step_no)
    started = time.monotonic()
    status = "OK"
    try:
        result = fn()
        return result
    except Exception:
        status = "ERROR"
        raise
    finally:
        db.add(AgentStep(
            agent=spec.name,
            tool=tool,
            args_hash=_hash_args(args),
            result_status=status,
            subject=(subject or "")[:64] or None,
            latency_ms=int((time.monotonic() - started) * 1000),
            correlation_id=correlation_id(),
        ))


def customer_intent(db: Session, text: str, *, subject: str | None = None) -> dict:
    db.add(LoopMetric(loop=CUSTOMER_CONVERSATION.name, event="ENTER", subject=subject))
    out = run_step(
        db, CUSTOMER_CONVERSATION, "extract_financial_intent",
        {"text_length": len(text)}, lambda: ai.extract_financial_intent(db, text, subject=subject),
        subject=subject,
    )
    db.add(LoopMetric(loop=CUSTOMER_CONVERSATION.name, event="COMPLETE", subject=subject))
    return out


def customer_profile_answer(
    db: Session, question: dict, text: str, *, subject: str | None = None
) -> tuple[Any, float]:
    return run_step(
        db, CUSTOMER_CONVERSATION, "extract_profile_facts",
        {"question_key": question.get("key"), "text_length": len(text)},
        lambda: ai.interpret_answer(db, question, text, subject=subject),
        subject=subject,
    )


def product_rules(db: Session, document_text: str, *, subject: str | None = None) -> dict:
    db.add(LoopMetric(loop=PRODUCT_CONFIGURATION.name, event="ENTER", subject=subject))
    out = run_step(
        db, PRODUCT_CONFIGURATION, "extract_product_rules",
        {"document_length": len(document_text)},
        lambda: ai.extract_product_rules(db, document_text, subject=subject),
        subject=subject,
    )
    db.add(LoopMetric(loop=PRODUCT_CONFIGURATION.name, event="COMPLETE", subject=subject))
    return out


def institution_tool(
    db: Session,
    tool: str,
    args: dict[str, Any] | None,
    fn: Callable[[], T],
    *,
    subject: str | None,
    step_no: int,
) -> T:
    return run_step(
        db, INSTITUTION_ASSISTANT, tool, args, fn, subject=subject, step_no=step_no
    )
