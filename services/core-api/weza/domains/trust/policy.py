"""RBAC permissions (TSD §48; blueprint 10 §2), Policy Decision Point (TSD §28) and the
Data Disclosure Gateway (TSD §29). Frontend hiding is never access control: every route checks here."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from weza.domains.trust.models import PolicyDecisionLog
from weza.platform.context import Actor
from weza.platform.errors import Forbidden, NotFound

POLICY_VERSION = "policies_v1"

INST_ROLES = ["INST_ADMIN", "EXECUTIVE", "BUSINESS", "CREDIT_RISK", "MANAGER", "OFFICER", "COMPLIANCE"]
WEZA_ROLES = ["WEZA_OPS", "WEZA_COMMERCIAL", "WEZA_SUPER"]

ROLE_LABELS = {
    "INST_ADMIN": "Administrator", "EXECUTIVE": "Executive", "BUSINESS": "Business / Product lead",
    "CREDIT_RISK": "Credit / Risk lead", "MANAGER": "Team manager", "OFFICER": "Relationship officer",
    "COMPLIANCE": "Compliance", "WEZA_OPS": "WEZA Operations", "WEZA_COMMERCIAL": "WEZA Commercial",
    "WEZA_SUPER": "WEZA Super-admin",
}

PERMISSIONS: dict[str, set[str]] = {
    "users.manage": {"INST_ADMIN", "WEZA_SUPER"},
    "institution.activate": {"INST_ADMIN"},
    "institution.settings": {"INST_ADMIN"},
    "product.read": {"INST_ADMIN", "EXECUTIVE", "BUSINESS", "CREDIT_RISK", "MANAGER", "OFFICER", "COMPLIANCE",
                     "WEZA_OPS", "WEZA_SUPER"},
    "product.create": {"BUSINESS", "CREDIT_RISK", "INST_ADMIN"},
    "product.approve": {"INST_ADMIN", "EXECUTIVE", "BUSINESS", "CREDIT_RISK"},
    "appetite.read": {"INST_ADMIN", "EXECUTIVE", "BUSINESS", "CREDIT_RISK", "MANAGER", "OFFICER", "COMPLIANCE",
                      "WEZA_OPS", "WEZA_SUPER"},
    "appetite.edit": {"INST_ADMIN", "BUSINESS", "CREDIT_RISK"},
    "appetite.simulate": {"BUSINESS", "CREDIT_RISK", "EXECUTIVE", "INST_ADMIN"},
    "appetite.activate": {"INST_ADMIN", "EXECUTIVE", "CREDIT_RISK"},
    "routing.manage": {"INST_ADMIN", "MANAGER"},
    "sandbox.run": {"INST_ADMIN", "BUSINESS", "CREDIT_RISK"},
    "opportunity.read_meta": {"INST_ADMIN", "EXECUTIVE", "BUSINESS", "CREDIT_RISK", "MANAGER", "OFFICER",
                              "COMPLIANCE", "WEZA_OPS", "WEZA_SUPER"},
    "opportunity.read_identifiable": {"INST_ADMIN", "MANAGER", "OFFICER", "COMPLIANCE"},
    "opportunity.assign": {"INST_ADMIN", "MANAGER"},
    "opportunity.update_status": {"MANAGER", "OFFICER"},
    "opportunity.request_info": {"MANAGER", "OFFICER"},
    "preview.read": {"EXECUTIVE", "BUSINESS", "CREDIT_RISK", "MANAGER"},
    "preview.interest": {"BUSINESS", "CREDIT_RISK", "MANAGER"},
    "team.manage": {"INST_ADMIN", "MANAGER"},
    "analytics.read": {"INST_ADMIN", "EXECUTIVE", "BUSINESS", "CREDIT_RISK", "MANAGER", "COMPLIANCE", "WEZA_OPS",
                       "WEZA_COMMERCIAL", "WEZA_SUPER"},
    "analytics.executive": {"INST_ADMIN", "EXECUTIVE", "BUSINESS", "CREDIT_RISK", "WEZA_OPS", "WEZA_SUPER"},
    "billing.view": {"INST_ADMIN", "EXECUTIVE", "WEZA_COMMERCIAL", "WEZA_SUPER", "WEZA_OPS"},
    "billing.dispute": {"INST_ADMIN", "EXECUTIVE"},
    "consent.audit": {"COMPLIANCE", "INST_ADMIN", "WEZA_OPS", "WEZA_SUPER"},
    "admin.verify_institution": {"WEZA_OPS", "WEZA_SUPER"},
    "admin.network_control": {"WEZA_OPS", "WEZA_SUPER"},
    "admin.config": {"WEZA_SUPER"},
    "admin.dispute_decide": {"WEZA_COMMERCIAL", "WEZA_SUPER"},
    "admin.vault_lookup": {"WEZA_OPS", "WEZA_SUPER"},
    "admin.read": {"WEZA_OPS", "WEZA_COMMERCIAL", "WEZA_SUPER"},
    "admin.review": {"WEZA_OPS", "WEZA_SUPER"},
    "admin.commercial": {"WEZA_COMMERCIAL", "WEZA_SUPER"},
}


def has(actor: Actor, permission: str) -> bool:
    return bool(actor.roles & PERMISSIONS.get(permission, set()))


def require(actor: Actor, permission: str) -> None:
    if not has(actor, permission):
        raise Forbidden("You don't have access to this — ask your administrator.", code="PERMISSION_DENIED",
                        details=[{"permission": permission}])


def officer_only(actor: Actor) -> bool:
    """A relationship officer with no broader institution role: sees and works only their assigned opportunities."""
    return "OFFICER" in actor.roles and not actor.roles & {"MANAGER", "INST_ADMIN", "EXECUTIVE", "BUSINESS",
                                                           "CREDIT_RISK", "COMPLIANCE"}


def require_tenant(actor: Actor, institution_id: uuid.UUID) -> None:
    """Cross-tenant requests return 404 so object existence is not leaked (AT-SEC-01)."""
    if actor.is_weza:
        return
    if actor.institution_id != institution_id:
        raise NotFound("Not found.")


def permissions_for(roles: frozenset[str] | set[str]) -> list[str]:
    return sorted(p for p, allowed in PERMISSIONS.items() if roles & allowed)


# ------------------------------------------------------------------ disclosure gateway

# Consent data categories → Level-3 fields (blueprint 10 §4)
CATEGORY_FIELDS = {
    "CONTACT": ["full_name", "phone", "email", "contact_channel", "contact_window"],
    "IDENTITY": ["nin", "identity_documents"],
    "PROFILE": ["business_name", "business_registered", "employer", "employment_type", "farm_activity",
                "district_detail"],
    "FINANCIAL": ["monthly_turnover", "monthly_income", "annual_income", "monthly_repayments"],
    "DOCUMENTS": ["documents"],
}
DEFAULT_CATEGORIES = ["CONTACT", "IDENTITY", "PROFILE", "FINANCIAL", "DOCUMENTS"]
FINANCIAL_FACTS = {"business.monthly_turnover", "employment.monthly_net_income", "farm.annual_income",
                   "finance.monthly_repayments"}


def fact_category(fact_key: str) -> str:
    """Consent category an institution needs before asking a customer for this profile field."""
    return "FINANCIAL" if fact_key in FINANCIAL_FACTS else "PROFILE"


@dataclass
class DisclosureDecision:
    result: str  # PERMIT | DENY | PERMIT_WITH_RESTRICTED_FIELDS
    fields: list[str] = field(default_factory=list)
    reason: str = ""


def decide_opportunity_access(db: Session, actor: Actor, opp, assignment, consent, purpose: str = "CONTACT") -> DisclosureDecision:
    """Authentication → Tenant → Role/Policy → Opportunity access → Consent → Data scope → Authorised fields."""
    decision = _decide(actor, opp, assignment, consent)
    db.add(PolicyDecisionLog(actor=f"{actor.kind}:{actor.id}", institution_id=opp.institution_id,
                             action="opportunity.view", resource=f"opportunity:{opp.id}", purpose=purpose,
                             result=decision.result, fields_permitted=decision.fields, policy_version=POLICY_VERSION))
    return decision


def _decide(actor: Actor, opp, assignment, consent) -> DisclosureDecision:
    if actor.is_weza:
        # WEZA staff see non-identifiable meta here; identity requires the audited vault lookup with a reason.
        return DisclosureDecision("PERMIT_WITH_RESTRICTED_FIELDS", [], "weza_staff_use_vault_lookup")
    if actor.institution_id != opp.institution_id:
        return DisclosureDecision("DENY", [], "tenant_mismatch")
    if not has(actor, "opportunity.read_meta"):
        return DisclosureDecision("DENY", [], "role")
    if not has(actor, "opportunity.read_identifiable"):
        return DisclosureDecision("PERMIT_WITH_RESTRICTED_FIELDS", [], "role_not_identifiable")
    if opp.integrity_hold or opp.state in ("QUALIFIED", "ROUTING_FAILED"):
        return DisclosureDecision("PERMIT_WITH_RESTRICTED_FIELDS", [], "not_routed")
    roles = actor.roles
    relationship = (
        "INST_ADMIN" in roles or "COMPLIANCE" in roles
        or ("MANAGER" in roles and (assignment is None or assignment.team_id is None or assignment.team_id == actor.team_id
                                    or actor.team_id is None))
        or ("OFFICER" in roles and assignment is not None and assignment.user_id == actor.id)
    )
    if not relationship:
        return DisclosureDecision("PERMIT_WITH_RESTRICTED_FIELDS", [], "not_assigned")
    if (consent is None or consent.status != "GRANTED" or consent.withdrawn_at is not None
            or consent.institution_id != opp.institution_id or consent.customer_id != opp.customer_id
            or consent.match_id != opp.match_id or consent.need_id != opp.need_id):
        return DisclosureDecision("PERMIT_WITH_RESTRICTED_FIELDS", [], "consent_not_valid")
    fields = [f for c in consent.data_categories for f in CATEGORY_FIELDS.get(c, [])]
    return DisclosureDecision("PERMIT", fields, "consented")
