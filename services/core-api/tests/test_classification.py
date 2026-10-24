"""Central data classification (TSD §49): disclosure, logging and document storage all consume one table."""

from tests.helpers import routed_to_lakeside
from weza.domains.customer.documents import DOC_TYPES
from weza.domains.trust.policy import CATEGORY_FIELDS
from weza.platform import classification
from weza.platform.logging import redact


def test_every_field_an_institution_can_be_shown_is_classified():
    shown = {f for fields in CATEGORY_FIELDS.values() for f in fields}
    assert shown <= set(classification.FIELDS), sorted(shown - set(classification.FIELDS))
    # the extra fields the opportunity page adds under CONTACT / PROFILE consent
    assert {"payout_phone", "business_registration_number", "trading_licence_number", "trading_licence_expiry",
            "credit_report", "date_of_birth"} <= set(classification.FIELDS)


def test_every_document_type_has_an_explicit_classification():
    assert set(DOC_TYPES) <= set(classification.DOCUMENTS)
    assert classification.document_level("national_id") == classification.HIGHLY_SENSITIVE
    assert classification.document_level("business_registration") == classification.CONFIDENTIAL


def test_anything_unknown_is_treated_as_the_most_sensitive():
    assert classification.level("a_field_nobody_classified") == classification.HIGHLY_SENSITIVE
    assert classification.document_level("a_new_document_type") == classification.HIGHLY_SENSITIVE
    assert not classification.is_classified("a_field_nobody_classified")
    assert classification.at_least("nin", classification.PERSONAL) and not classification.at_least("business_name", classification.PERSONAL)


def test_logs_redact_personal_and_highly_sensitive_fields_but_not_everything():
    out = redact({"nin": "CM12345678ABCD", "payout_phone": "+256772000001", "date_of_birth": "1990-04-02",
                  "full_name": "Grace", "otp": "123456", "authorization": "Bearer x", "credit_report": {"score": 700},
                  "amount": 5_000_000, "state": "ROUTED", "updated_at": "2026-10-24", "business_name": "Nakato Traders"})
    for key in ("nin", "payout_phone", "date_of_birth", "full_name", "otp", "authorization", "credit_report"):
        assert out[key] == "[REDACTED]", key
    assert out["amount"] == 5_000_000 and out["state"] == "ROUTED" and out["updated_at"] == "2026-10-24"
    assert out["business_name"] == "[REDACTED]"  # also caught by the broad "name" rule kept from before


def test_a_field_the_classification_does_not_know_is_never_shown_to_an_institution(client, as_user, journey, monkeypatch):
    _, oid, owner = routed_to_lakeside(journey, "0772480902")
    headers = as_user(owner)
    shown = client.get(f"/api/v1/inst/opportunities/{oid}", headers=headers).json()["customer"]["fields"]
    assert "phone" in shown and "full_name" in shown
    monkeypatch.setattr(classification, "FIELDS", {k: v for k, v in classification.FIELDS.items() if k != "phone"})
    after = client.get(f"/api/v1/inst/opportunities/{oid}", headers=headers).json()["customer"]["fields"]
    assert "phone" not in after and "full_name" in after  # fail closed: unclassified means not disclosed
