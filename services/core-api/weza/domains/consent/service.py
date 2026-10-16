"""Consent service (FSD §13, TSD §27). Institution-specific, versioned, text-hashed, withdrawable."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.domains.consent.models import Consent, ConsentTemplate
from weza.domains.trust.policy import DEFAULT_CATEGORIES
from weza.domains.trust.service import audit
from weza.platform.context import Actor
from weza.platform.crypto import sha256_hex
from weza.platform.db import utcnow
from weza.platform.errors import NotFound, ValidationFailed
from weza.platform.events import emit

PURPOSE = "INSTITUTION_CONTACT_FOR_FINANCING"

CATEGORY_LABELS = {
    "CONTACT": "Contact details (name, phone, preferred contact time)",
    "IDENTITY": "Identity details (National ID number, if provided)",
    "PROFILE": "Business / employment / farm profile",
    "FINANCIAL": "Financial information you gave WEZA (turnover or income, existing repayments)",
    "DOCUMENTS": "Documents you uploaded to WEZA",
}

DEFAULT_TEXT = (
    "By agreeing, you allow WEZA to share the information listed below with {institution} so that they can contact "
    "you about your financing request.\n\n"
    "• WEZA is a marketplace, not a lender. {institution} will carry out its own checks (including identity "
    "verification) and makes its own decision. A match is not a loan approval.\n"
    "• Your phone number is used for contact only. It is not treated as a payment or disbursement destination.\n"
    "• Your information will not be shared with any other institution unless you give separate consent.\n"
    "• You can withdraw this consent at any time in WEZA. Withdrawal stops future sharing by WEZA, but cannot "
    "remove information {institution} has already lawfully received.\n"
    "• Processing follows Uganda's Data Protection and Privacy Act, 2019."
)


def current_template(db: Session, country: str = "UG", language: str = "en") -> ConsentTemplate:
    t = db.execute(select(ConsentTemplate).where(ConsentTemplate.country_code == country,
                                                 ConsentTemplate.purpose == PURPOSE,
                                                 ConsentTemplate.language == language,
                                                 ConsentTemplate.status == "PUBLISHED")
                   .order_by(ConsentTemplate.effective_from.desc()).limit(1)).scalar_one_or_none()
    if t is None:
        t = ConsentTemplate(country_code=country, purpose=PURPOSE, version="2026.1", language=language,
                            title="Share my request with {institution}", text=DEFAULT_TEXT,
                            text_hash=sha256_hex(DEFAULT_TEXT))
        db.add(t)
        db.flush()
    return t


def publish_template(db: Session, actor: Actor, *, title: str, text: str, reason: str, country: str = "UG",
                     language: str = "en") -> ConsentTemplate:
    """Publish a new consent version (TSD §71–72). Published text is never edited: the previous version is retired
    and a new row is written. Consents already granted keep the version and text hash they were shown."""
    title, text = title.strip(), text.strip()
    try:
        title.format(institution="X"), text.format(institution="X")
    except (KeyError, IndexError, ValueError) as exc:
        raise ValidationFailed("Only the {institution} placeholder may be used in curly braces.") from exc
    if "{institution}" not in text:
        raise ValidationFailed("The consent text must name the institution using {institution}.")
    current = current_template(db, country, language)
    if sha256_hex(text) == current.text_hash and title == current.title:
        raise ValidationFailed("This is the same as the current version.")
    year = utcnow().year
    used = set(db.execute(select(ConsentTemplate.version).where(ConsentTemplate.country_code == country,
                                                                ConsentTemplate.purpose == PURPOSE,
                                                                ConsentTemplate.language == language)).scalars())
    n = 1
    while f"{year}.{n}" in used:
        n += 1
    current.status = "RETIRED"
    tpl = ConsentTemplate(country_code=country, purpose=PURPOSE, version=f"{year}.{n}", language=language, title=title,
                          text=text, text_hash=sha256_hex(text), effective_from=utcnow())
    db.add(tpl)
    db.flush()
    audit(db, actor, "consent_template.published", "consent_template", tpl.id, reason=reason,
          before={"version": current.version, "text_hash": current.text_hash},
          after={"version": tpl.version, "text_hash": tpl.text_hash})
    return tpl


def template_history(db: Session, country: str = "UG", language: str = "en") -> list[ConsentTemplate]:
    return list(db.execute(select(ConsentTemplate).where(ConsentTemplate.country_code == country,
                                                         ConsentTemplate.purpose == PURPOSE,
                                                         ConsentTemplate.language == language)
                           .order_by(ConsentTemplate.effective_from.desc())).scalars())


def render(template: ConsentTemplate, institution_name: str) -> dict:
    return {"template_id": str(template.id), "version": template.version,
            "title": template.title.format(institution=institution_name),
            "text": template.text.format(institution=institution_name), "purpose": template.purpose,
            "categories": [{"code": c, "label": CATEGORY_LABELS[c]} for c in DEFAULT_CATEGORIES]}


def grant(db: Session, actor: Actor, *, customer_id: uuid.UUID, institution_id: uuid.UUID, need_id: uuid.UUID,
          match_id: uuid.UUID, template_id: uuid.UUID, categories: list[str] | None = None, channel: str = "web",
          contact_channel: str = "phone", contact_window: str = "ANY") -> Consent:
    existing = db.execute(select(Consent).where(Consent.match_id == match_id)).scalar_one_or_none()
    if existing and existing.status == "GRANTED":
        return existing  # idempotent per match
    tpl = db.get(ConsentTemplate, template_id)
    if tpl is None or tpl.status != "PUBLISHED":
        raise ValidationFailed("This consent text is no longer current. Please review the latest version.",
                               code="CONSENT_TEMPLATE_STALE")
    cats = [c for c in (categories or DEFAULT_CATEGORIES) if c in CATEGORY_LABELS]
    if "CONTACT" not in cats:
        raise ValidationFailed("Contact details must be shared for an institution to reach you.",
                               code="CONSENT_CONTACT_REQUIRED")
    c = existing or Consent(customer_id=customer_id, institution_id=institution_id, need_id=need_id, match_id=match_id)
    c.purpose, c.data_categories, c.template_id, c.template_version = PURPOSE, cats, tpl.id, tpl.version
    c.text_hash, c.status, c.channel, c.granted_at = tpl.text_hash, "GRANTED", channel, utcnow()
    c.contact_channel, c.contact_window = contact_channel, contact_window
    if existing is None:
        db.add(c)
    db.flush()
    audit(db, actor, "consent.granted", "consent", c.id, institution_id=institution_id,
          after={"categories": cats, "version": tpl.version, "text_hash": tpl.text_hash})
    emit(db, "ConsentGranted", topic="opportunity", aggregate_type="consent", aggregate_id=c.id,
         institution_id=institution_id, data={"need_id": str(need_id), "match_id": str(match_id)})
    return c


def withdraw(db: Session, actor: Actor, consent_id: uuid.UUID, customer_id: uuid.UUID, reason: str | None = None) -> Consent:
    c = db.get(Consent, consent_id)
    if c is None or c.customer_id != customer_id:
        raise NotFound("Consent not found.")
    if c.status == "WITHDRAWN":
        return c
    c.status, c.withdrawn_at, c.withdraw_reason = "WITHDRAWN", utcnow(), reason
    audit(db, actor, "consent.withdrawn", "consent", c.id, institution_id=c.institution_id, reason=reason)
    emit(db, "ConsentWithdrawn", topic="opportunity", aggregate_type="consent", aggregate_id=c.id,
         institution_id=c.institution_id, data={"opportunity_id": str(c.opportunity_id) if c.opportunity_id else None})
    return c


def is_valid(c: Consent | None, institution_id: uuid.UUID) -> bool:
    return c is not None and c.status == "GRANTED" and c.institution_id == institution_id
