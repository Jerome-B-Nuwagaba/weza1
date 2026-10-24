"""TSD §9 structured AI output: DocumentClassification, MatchExplanation and InstitutionQuery. The model is replaced by
fixed answers; what is tested is everything WEZA does with them: validation, confidence, forbidden claims, fallbacks."""

import pytest

from tests.test_whatsapp_channel import (  # noqa: F401 — fixtures are picked up by name
    PNG,
    fake_phone,
    http,
    media_msg,
    stored_docs,
    verified_journey,
    wa_inbound,
    wa_live,
)
from weza.config import get_settings
from weza.domains.intelligence import ai, assistant
from weza.domains.intelligence.ai import DocumentClassificationV1, InstitutionQueryV1, MatchExplanationV1
from weza.platform.context import Actor
from weza.platform.db import session_scope

TOOLS = {"search_opportunities": {"sector", "min_match", "customer_type", "limit"}, "get_demand_summary": set(),
         "simulate_appetite": {"field", "op", "value"}}


@pytest.fixture()
def model(monkeypatch):
    """Whatever the 'model' should answer next, as the schema object; `calls` records what was asked."""
    state = {"answer": None, "calls": []}

    def fake_call(db, capability, schema, system, user, **kw):
        state["calls"].append(capability)
        return state["answer"]
    monkeypatch.setattr(ai, "_call", fake_call)
    return state


# ------------------------------------------------------------------ DocumentClassification


def test_a_confident_known_document_type_is_returned(model):
    model["answer"] = DocumentClassificationV1(doc_type="bank_statement", legible=True, confidence=0.93)
    with session_scope() as db:
        assert ai.classify_document(db, "image/png", PNG) == {"doc_type": "bank_statement", "legible": True, "confidence": 0.93}


@pytest.mark.parametrize("answer", [DocumentClassificationV1(doc_type="passport_of_mars", confidence=0.99),
                                    DocumentClassificationV1(doc_type="product_document", confidence=0.99), None])
def test_an_unknown_or_institution_only_type_or_no_answer_is_not_accepted(model, answer):
    model["answer"] = answer
    with session_scope() as db:
        assert ai.classify_document(db, "image/png", PNG) is None


def test_classification_is_off_when_document_reading_is_off(model, monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_document_extraction", False)
    with session_scope() as db:
        assert ai.classify_document(db, "image/png", PNG) is None
    assert model["calls"] == []  # the document was never sent anywhere


def test_a_whatsapp_upload_with_no_caption_is_classified_after_it_is_stored(client, wa_live, http, monkeypatch):
    seen = []
    phone = fake_phone()
    j = verified_journey(client, phone)  # first, while document reading is still off, so the journey goes to the questions
    monkeypatch.setattr(ai, "can_read_documents", lambda db: True)

    def classify(db, mime, data, subject=None):
        seen.append(len(data))
        return {"doc_type": "bank_statement", "legible": True, "confidence": 0.92}
    monkeypatch.setattr(ai, "classify_document", classify)
    http.media["CL1"] = (PNG, "image/png")
    media_msg(client, phone, "image", "CL1")  # no caption, so nothing says what it is
    (d,) = stored_docs(j["customer_id"])
    assert d.pipeline_state == "STORED" and d.doc_type == "bank_statement" and d.classification == "HIGHLY_SENSITIVE"
    assert seen == [len(PNG)]  # sent only after it had been stored (so scanned)


def test_a_captioned_upload_is_never_second_guessed_and_a_doubtful_answer_is_ignored(client, wa_live, http, monkeypatch):
    calls = []
    phone = fake_phone()
    j = verified_journey(client, phone)
    monkeypatch.setattr(ai, "can_read_documents", lambda db: True)

    def classify(db, mime, data, subject=None):
        calls.append(1)
        return {"doc_type": "payslip", "legible": True, "confidence": 0.5}  # not sure enough
    monkeypatch.setattr(ai, "classify_document", classify)
    http.media["CL2"] = (PNG, "image/png")
    media_msg(client, phone, "image", "CL2", caption="my bank statement")
    assert calls == [] and stored_docs(j["customer_id"])[0].doc_type == "bank_statement"
    http.media["CL3"] = (PNG, "image/png")
    media_msg(client, phone, "image", "CL3")  # no caption, but the model is only 50% sure
    assert calls == [1] and "payslip" not in {d.doc_type for d in stored_docs(j["customer_id"])}  # 50% sure is not enough


# ------------------------------------------------------------------ MatchExplanation

REASONS = {"matched": [{"text": "Amount within range"}, {"text": "Target sector"}], "near_miss": [], "outstanding": []}


def test_a_plain_wording_of_the_reasons_is_used(model):
    model["answer"] = MatchExplanationV1(summary="Your amount and sector fit what this lender is looking for.")
    with session_scope() as db:
        assert ai.explain_match(db, REASONS, "fallback") == "Your amount and sector fit what this lender is looking for."


@pytest.mark.parametrize("promise", ["You will definitely be approved.", "This loan is guaranteed.",
                                     "Approved! You will get the money."])
def test_any_wording_that_promises_credit_is_thrown_away(model, promise):
    model["answer"] = MatchExplanationV1(summary=promise)
    with session_scope() as db:
        assert ai.explain_match(db, REASONS, "the deterministic wording") == "the deterministic wording"


def test_no_reasons_means_no_model_call_and_no_answer_means_the_fallback(model):
    with session_scope() as db:
        assert ai.explain_match(db, {"matched": [], "near_miss": [], "outstanding": []}, "fallback") == "fallback"
        assert model["calls"] == []
        model["answer"] = None
        assert ai.explain_match(db, REASONS, "fallback") == "fallback"


def test_the_wording_is_capped_in_length(model):
    model["answer"] = MatchExplanationV1(summary="Fits your needs. " * 60)
    with session_scope() as db:
        assert len(ai.explain_match(db, REASONS, "fallback")) <= 280


# ------------------------------------------------------------------ InstitutionQuery


def test_a_valid_proposal_becomes_a_validated_tool_call(model):
    model["answer"] = InstitutionQueryV1(tool="search_opportunities", sector="retail_trade", customer_type="SME",
                                         min_match=80, limit=5, confidence=0.9)
    with session_scope() as db:
        plan = ai.parse_institution_query(db, "show me the strongest shops", TOOLS)
    assert plan == {"tool": "search_opportunities",
                    "args": {"sector": "retail_trade", "customer_type": "SME", "min_match": 80, "limit": 5}}


def test_invalid_fields_are_dropped_and_arguments_the_tool_does_not_take_are_removed(model):
    model["answer"] = InstitutionQueryV1(tool="get_demand_summary", sector="made_up_sector", min_match=150, limit=500,
                                         customer_type="ROBOT", confidence=0.9)
    with session_scope() as db:
        assert ai.parse_institution_query(db, "demand?", TOOLS) == {"tool": "get_demand_summary", "args": {}}
    model["answer"] = InstitutionQueryV1(tool="search_opportunities", sector="made_up_sector", min_match=150,
                                         customer_type="ROBOT", confidence=0.9)
    with session_scope() as db:
        assert ai.parse_institution_query(db, "x", TOOLS)["args"] == {}  # nothing invalid survives


@pytest.mark.parametrize("answer", [InstitutionQueryV1(tool="delete_everything", confidence=0.99),
                                    InstitutionQueryV1(tool="get_demand_summary", confidence=0.3), None])
def test_an_unknown_tool_a_doubtful_guess_or_no_answer_is_no_plan(model, answer):
    model["answer"] = answer
    with session_scope() as db:
        assert ai.parse_institution_query(db, "something", TOOLS) is None


def _actor() -> Actor:
    return Actor(kind="INSTITUTION_USER", display="t", institution_id=None, roles=frozenset({"MANAGER"}))


def test_recognised_questions_use_the_keyword_rules_and_never_ask_the_model(monkeypatch):
    monkeypatch.setattr(ai, "effective_mode", lambda db: "AVAILABLE")
    monkeypatch.setattr(assistant.agents, "parse_institution_query",
                        lambda *a, **k: pytest.fail("the model was asked about a question the rules understand"))
    with session_scope() as db:
        assert assistant._plan(db, _actor(), "Where is demand coming from?")[0][0] == "get_demand_summary"
        assert assistant._plan(db, _actor(), "How is my team's queue?")[0][0] == "get_team_queue"


def test_an_unrecognised_question_uses_the_models_proposal_when_it_is_valid(monkeypatch):
    monkeypatch.setattr(ai, "effective_mode", lambda db: "AVAILABLE")
    monkeypatch.setattr(assistant.agents, "parse_institution_query",
                        lambda db, q, tools, subject=None: {"tool": "get_near_match_analysis", "args": {}})
    with session_scope() as db:
        assert assistant._plan(db, _actor(), "Anything surprising lately?") == [("get_near_match_analysis", {})]


def test_without_a_proposal_or_without_ai_an_unrecognised_question_gets_the_plain_search(monkeypatch):
    with session_scope() as db:
        monkeypatch.setattr(ai, "effective_mode", lambda db: "UNAVAILABLE")
        assert assistant._plan(db, _actor(), "Anything surprising lately?") == [("search_opportunities", {})]
        monkeypatch.setattr(ai, "effective_mode", lambda db: "AVAILABLE")
        monkeypatch.setattr(assistant.agents, "parse_institution_query", lambda *a, **k: None)
        assert assistant._plan(db, _actor(), "Anything surprising lately?") == [("search_opportunities", {})]
        monkeypatch.setattr(assistant.agents, "parse_institution_query",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("provider down")))
        assert assistant._plan(db, _actor(), "Anything surprising lately?") == [("search_opportunities", {})]
