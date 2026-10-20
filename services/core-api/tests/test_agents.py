"""Agent supervisor: allow-lists, auditability and deterministic fallbacks."""

import pytest
from sqlalchemy import select

from weza.domains.intelligence import agents
from weza.domains.misc_models import AgentStep
from weza.platform.db import session_scope


def test_agent_supervisor_blocks_business_authority():
    called = []

    with session_scope() as db:
        for tool in ("crb.enquire", "consent.grant", "matching.rank", "appetite.activate", "credit.approve"):
            with pytest.raises(agents.AgentPolicyError):
                agents.run_step(
                    db,
                    agents.INSTITUTION_ASSISTANT,
                    tool,
                    {},
                    lambda: called.append(tool),
                    subject="policy-test",
                )
    assert called == []


def test_agent_supervisor_enforces_each_agents_tool_allowlist():
    with session_scope() as db:
        with pytest.raises(agents.AgentPolicyError):
            agents.run_step(
                db,
                agents.CUSTOMER_CONVERSATION,
                "simulate_appetite",
                {},
                lambda: {"should": "not run"},
                subject="customer-test",
            )
        with pytest.raises(agents.AgentPolicyError):
            agents.run_step(
                db,
                agents.PRODUCT_CONFIGURATION,
                "search_opportunities",
                {},
                lambda: {"should": "not run"},
                subject="product-test",
            )


def test_customer_conversation_agent_logs_safe_step_without_raw_text():
    marker = "AGENT-PRIVATE-CUSTOMER-TEXT-4412"
    subject = "agent-customer-test"
    with session_scope() as db:
        result = agents.customer_intent(
            db, f"I need UGX 5 million for stock {marker}", subject=subject
        )
        assert result["amount"] == 5_000_000

    with session_scope() as db:
        step = db.execute(
            select(AgentStep).where(
                AgentStep.subject == subject,
                AgentStep.agent == "customer_conversation",
                AgentStep.tool == "extract_financial_intent",
            )
        ).scalar_one()
        assert step.result_status == "OK"
        assert len(step.args_hash) == 64
        blob = f"{step.agent} {step.tool} {step.args_hash} {step.subject}"
        assert marker not in blob


def test_marketplace_agent_falls_back_without_provider_and_logs_step():
    subject = "marketplace-agent-test"
    fallback = "Aggregated demand is stable. Review the evidence before changing policy."
    with session_scope() as db:
        text = agents.marketplace_narrative(
            db,
            "narrate_insight",
            {"count": 12, "share": 0.5},
            fallback,
            subject=subject,
        )
        assert text == fallback

    with session_scope() as db:
        step = db.execute(
            select(AgentStep).where(
                AgentStep.subject == subject,
                AgentStep.agent == "marketplace_intelligence",
            )
        ).scalar_one()
        assert step.tool == "narrate_insight" and step.result_status == "OK"
