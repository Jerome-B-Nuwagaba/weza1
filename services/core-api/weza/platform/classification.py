"""Central data classification (TSD §49): one place that says how sensitive each field and document type is.

Fields and objects are PUBLIC, INTERNAL, CONFIDENTIAL, PERSONAL or HIGHLY_SENSITIVE. Security, logging, retention and
disclosure all consume this table instead of keeping their own lists:
- disclosure: a field that is not classified here is never shown to an institution (fail closed);
- logging: PERSONAL and HIGHLY_SENSITIVE field names are redacted from structured logs;
- documents: the stored file is classified from its type when it is ingested.
Anything unknown is treated as HIGHLY_SENSITIVE.
"""

PUBLIC, INTERNAL, CONFIDENTIAL, PERSONAL, HIGHLY_SENSITIVE = "PUBLIC", "INTERNAL", "CONFIDENTIAL", "PERSONAL", "HIGHLY_SENSITIVE"
LEVELS = (PUBLIC, INTERNAL, CONFIDENTIAL, PERSONAL, HIGHLY_SENSITIVE)  # least to most sensitive

#: Customer fields an institution may be shown, once the customer has consented (the disclosure gateway, TSD §28).
FIELDS: dict[str, str] = {
    # who they are
    "full_name": PERSONAL, "phone": PERSONAL, "email": PERSONAL, "payout_phone": PERSONAL,
    "nin": HIGHLY_SENSITIVE, "date_of_birth": HIGHLY_SENSITIVE, "identity_documents": HIGHLY_SENSITIVE,
    "contact_channel": CONFIDENTIAL, "contact_window": CONFIDENTIAL,
    # their business and work
    "business_name": CONFIDENTIAL, "business_registered": CONFIDENTIAL, "business_registration_number": CONFIDENTIAL,
    "trading_licence_number": CONFIDENTIAL, "trading_licence_expiry": CONFIDENTIAL, "employer": CONFIDENTIAL,
    "employment_type": CONFIDENTIAL, "farm_activity": CONFIDENTIAL, "district_detail": CONFIDENTIAL,
    # what they earn and owe
    "monthly_turnover": CONFIDENTIAL, "monthly_income": PERSONAL, "annual_income": PERSONAL,
    "monthly_repayments": PERSONAL,
    # files and bureau data
    "documents": HIGHLY_SENSITIVE, "credit_report": HIGHLY_SENSITIVE,
}

#: Stored customer documents, by type (TSD §51). Unknown types are HIGHLY_SENSITIVE.
DOCUMENTS: dict[str, str] = {
    "national_id": HIGHLY_SENSITIVE, "bank_statement": HIGHLY_SENSITIVE, "mobile_money_statement": HIGHLY_SENSITIVE,
    "payslip": PERSONAL, "employment_letter": PERSONAL, "business_registration": CONFIDENTIAL,
    "trading_licence": CONFIDENTIAL, "farm_records": CONFIDENTIAL, "product_document": INTERNAL, "other": PERSONAL,
}

#: Field names in logs and payloads that are always redacted, whatever the field table says (secrets are not "data").
ALWAYS_REDACTED = ("otp", "code", "password", "secret", "token", "authorization", "document", "address", "dob")


def level(field: str) -> str:
    return FIELDS.get(field, HIGHLY_SENSITIVE)


def is_classified(field: str) -> bool:
    return field in FIELDS


def document_level(doc_type: str) -> str:
    return DOCUMENTS.get(doc_type, HIGHLY_SENSITIVE)


def at_least(field: str, minimum: str) -> bool:
    return LEVELS.index(level(field)) >= LEVELS.index(minimum)


def redacted_key_fragments() -> list[str]:
    """Key names that logging redacts: every PERSONAL or HIGHLY_SENSITIVE field name, plus the secrets."""
    return sorted({*ALWAYS_REDACTED, *(f for f in FIELDS if at_least(f, PERSONAL))})
