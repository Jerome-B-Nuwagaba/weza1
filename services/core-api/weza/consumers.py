"""Event consumers — the wiring of WEZA's loops (blueprint 06, 08). Each consumer is idempotent and runs in its own
transaction via the outbox dispatcher; critical consumers dead-letter with an operational alert."""

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from weza.domains.customer.models import Customer
from weza.domains.institution.models import Institution
from weza.domains.matching import engine
from weza.domains.matching.models import Match
from weza.domains.misc_models import Notification
from weza.domains.need.models import FinancialNeed
from weza.domains.notification import service as notify
from weza.domains.opportunity import service as opp_svc
from weza.domains.opportunity.models import Assignment, Opportunity, Preview
from weza.domains.trust.service import audit
from weza.platform.context import SYSTEM
from weza.platform.controls import flag
from weza.platform.db import utcnow
from weza.platform.events import consumer
from weza.platform.models import OutboxEvent


def _opp(db: Session, ev: OutboxEvent) -> Opportunity | None:
    return db.get(Opportunity, uuid.UUID(ev.aggregate_id))


def _money(v) -> str:
    from weza.domains.matching.rules import fmt_money
    return fmt_money(v)


# ------------------------------------------------------------------ WhatsApp inbound (ack fast, process here)


@consumer("whatsapp_inbound", ["WhatsAppInboundReceived"])
def on_whatsapp_inbound(db: Session, ev: OutboxEvent) -> None:
    from weza.domains.misc_models import WhatsappInbox
    from weza.domains.notification import whatsapp_inbound
    row = db.get(WhatsappInbox, uuid.UUID(ev.aggregate_id))
    if row is not None and row.status == "PENDING":
        whatsapp_inbound.process_phone(db, row.phone_index)


# ------------------------------------------------------------------ routing → assignment → billing → notifications


@consumer("assignment", ["OpportunityRouted"], critical=True)
def on_routed_assign(db: Session, ev: OutboxEvent) -> None:
    opp = _opp(db, ev)
    if opp is not None:
        opp_svc.assign_by_rules(db, opp)


@consumer("billing", ["OpportunityRouted"], critical=True)
def on_routed_bill(db: Session, ev: OutboxEvent) -> None:
    opp = _opp(db, ev)
    if opp is not None:
        from weza.domains.commercial.service import on_opportunity_routed
        on_opportunity_routed(db, opp)


@consumer("notify_routed", ["OpportunityRouted"], critical=True)
def on_routed_notify(db: Session, ev: OutboxEvent) -> None:
    opp = _opp(db, ev)
    if opp is None:
        return
    inst = db.get(Institution, opp.institution_id)
    high = opp.priority in ("HIGH", "URGENT")
    title = f"{'High-match' if opp.match_score >= 90 else 'New'} opportunity {opp.reference}: {_money(opp.amount)}"
    body = f"{(opp.snapshot.get('need') or {}).get('purpose') or opp.purpose_category} · {opp.district or ''} · match {round(opp.match_score)}"
    notify.notify_institution(db, opp.institution_id, "HighMatchOpportunity" if high else "OpportunityRouted",
                              title=title, body=body, link=f"/institution/opportunities/{opp.id}",
                              priority=opp.priority if high else "NORMAL", roles=["MANAGER"],
                              object_type="opportunity", object_id=str(opp.id), ack_required=high,
                              event_id=ev.id, dedupe=f"routed:{opp.id}")
    notify.notify_customer(db, opp.customer_id, "OpportunityRouted", title="Request shared",
                           body=f"Your request {opp.reference} has been shared with {inst.display_name}. They'll "
                                "contact you directly.", link="/c/status", object_type="opportunity",
                           object_id=str(opp.id))


@consumer("notify_assigned", ["OpportunityAssigned", "OpportunityUnassigned"])
def on_assigned(db: Session, ev: OutboxEvent) -> None:
    opp = _opp(db, ev)
    if opp is None:
        return
    if ev.event_type == "OpportunityAssigned" and ev.data.get("user_id"):
        uid = uuid.UUID(ev.data["user_id"])
        notify.notify_institution(db, opp.institution_id, "OpportunityAssigned",
                                  title=f"Assigned to you: {opp.reference} · {_money(opp.amount)}",
                                  body=f"Match {round(opp.match_score)} · first contact target applies",
                                  link=f"/institution/opportunities/{opp.id}", priority=opp.priority,
                                  user_ids=[uid], object_type="opportunity", object_id=str(opp.id),
                                  ack_required=opp.priority != "NORMAL", event_id=ev.id, dedupe=f"assigned:{ev.id}")
    else:
        notify.notify_institution(db, opp.institution_id, "OpportunityUnassigned",
                                  title=f"Unassigned opportunity {opp.reference} needs an owner",
                                  body="No routing rule matched.", link="/institution/feed?view=unassigned",
                                  priority="HIGH", roles=["MANAGER", "INST_ADMIN"], object_type="opportunity",
                                  object_id=str(opp.id), event_id=ev.id, dedupe=f"unassigned:{opp.id}")


@consumer("notify_service_targets", ["ServiceTargetApproaching", "ServiceTargetBreached", "ServiceTargetEscalated"])
def on_service_target(db: Session, ev: OutboxEvent) -> None:
    opp = _opp(db, ev)
    if opp is None:
        return
    a = db.get(Assignment, opp.id)
    uid = [a.user_id] if a and a.user_id else None
    if ev.event_type == "ServiceTargetApproaching":
        notify.notify_institution(db, opp.institution_id, "ServiceTargetApproaching",
                                  title=f"First contact due soon: {opp.reference}", link=f"/institution/opportunities/{opp.id}",
                                  priority="HIGH", user_ids=uid, roles=None if uid else ["MANAGER"],
                                  object_type="opportunity", object_id=str(opp.id), dedupe=f"approach:{opp.id}")
    elif ev.event_type == "ServiceTargetBreached":
        notify.notify_institution(db, opp.institution_id, "ServiceTargetBreached",
                                  title=f"Service target breached: {opp.reference} not yet contacted",
                                  link=f"/institution/opportunities/{opp.id}", priority="URGENT", user_ids=uid,
                                  roles=["MANAGER"], object_type="opportunity", object_id=str(opp.id),
                                  ack_required=True, dedupe=f"breach:{opp.id}")
    else:
        notify.notify_weza_ops(db, "ServiceTargetEscalated", f"{opp.reference}: institution non-response",
                               link=f"/admin/graph?q={opp.reference}", object_type="opportunity", object_id=str(opp.id))
        inst = db.get(Institution, opp.institution_id)
        notify.notify_customer(db, opp.customer_id, "InstitutionNonResponse", title="We're following up",
                               body=f"{inst.display_name} hasn't contacted you yet about {opp.reference}. We've "
                                    "reminded them. You can also withdraw and choose another option in WEZA.",
                               link="/c/status")


@consumer("customer_status_updates", ["OpportunityStatusChanged", "OutcomeReported", "OpportunityReceived"])
def on_status(db: Session, ev: OutboxEvent) -> None:
    opp = _opp(db, ev)
    if opp is None:
        return
    inst = db.get(Institution, opp.institution_id)
    state = ev.data.get("to") or ev.data.get("state")
    if ev.event_type == "OpportunityStatusChanged" and state not in ("CONTACTED", "SUBMITTED_TO_INSTITUTION"):
        return  # outcome states are announced once, from OutcomeReported
    messages = {
        "CONTACTED": f"{inst.display_name} has marked your request {opp.reference} as contacted.",
        "SUBMITTED_TO_INSTITUTION": f"{inst.display_name} reports your application is in their process.",
        "REPORTED_APPROVED": f"{inst.display_name} reports your request {opp.reference} was approved. "
                             + ("Their indicative terms are in WEZA — confirm the final offer with them directly."
                                if ev.data.get("has_terms") else "They will share terms directly with you."),
        "REPORTED_DISBURSED": f"{inst.display_name} reports funds for {opp.reference} have been disbursed.",
    }
    if state in messages:
        notify.notify_customer(db, opp.customer_id, f"Opportunity{state.title()}", title="Update on your request",
                               body=messages[state], link="/c/status", object_type="opportunity", object_id=str(opp.id))
    if ev.event_type == "OutcomeReported" and state == "REPORTED_DECLINED":
        need = db.get(FinancialNeed, opp.need_id)
        notify.notify_customer(db, opp.customer_id, "OpportunityDeclined", title="An update on your request",
                               body=f"{inst.display_name} can't proceed with {opp.reference}. WEZA can check other "
                                    "institutions for you — open WEZA to choose.", link="/start")
        if need and need.journey_id:
            from weza.domains.need.service import system_resume
            from weza.platform.models import GraphInstance
            gi = db.get(GraphInstance, need.journey_id)
            if gi and gi.current_node == "TRACKING":
                system_resume(db, need.journey_id, "_declined", str(opp.id), reason=ev.data.get("reason"))


@consumer("consent_withdrawn_notify", ["ConsentWithdrawn"])
def on_consent_withdrawn(db: Session, ev: OutboxEvent) -> None:
    oid = ev.data.get("opportunity_id")
    if not oid:
        return
    opp = db.get(Opportunity, uuid.UUID(oid))
    if opp is None:
        return
    opp_svc.close_open_info_requests(db, opp, "Customer withdrew consent")
    a = db.get(Assignment, opp.id)
    notify.notify_institution(db, opp.institution_id, "ConsentWithdrawn",
                              title=f"Customer withdrew consent for {opp.reference}",
                              body="WEZA will no longer disclose this customer's details. Information you already "
                                   "received remains under your own obligations.",
                              link=f"/institution/opportunities/{opp.id}", priority="HIGH",
                              user_ids=[a.user_id] if a and a.user_id else None, roles=["MANAGER", "COMPLIANCE"],
                              object_type="opportunity", object_id=str(opp.id), dedupe=f"withdrawn:{ev.id}")


@consumer("info_requests_notify", ["InfoRequested", "InfoRequestFulfilled", "InfoRequestCancelled",
                                   "InfoRequestExpired"])
def on_info_request(db: Session, ev: OutboxEvent) -> None:
    opp = _opp(db, ev)
    if opp is None:
        return
    inst = db.get(Institution, opp.institution_id)
    if ev.event_type == "InfoRequested":
        what = "a document" if ev.data.get("kind") == "DOCUMENT" else "some information"
        notify.notify_customer(db, opp.customer_id, "InfoRequested", title=f"{inst.display_name} asked for {what}",
                               body=f"About your request {opp.reference}. Open WEZA to see what they need — you choose "
                                    "whether to answer. WEZA will never ask for your PIN or password.",
                               link="/c/status", object_type="info_request", object_id=ev.data.get("request_id"))
    elif ev.event_type == "InfoRequestCancelled":
        notify.notify_customer(db, opp.customer_id, "InfoRequestCancelled", title="A request was withdrawn",
                               body=f"{inst.display_name} no longer needs the item they asked for on {opp.reference}.",
                               link="/c/status", object_type="info_request", object_id=ev.data.get("request_id"))
    elif ev.event_type == "InfoRequestExpired":
        a = db.get(Assignment, opp.id)
        notify.notify_institution(db, opp.institution_id, "InfoRequestExpired",
                                  title=f"No answer in time on {opp.reference}",
                                  body="Your request to the customer expired. Contact them directly or ask again.",
                                  link=f"/institution/opportunities/{opp.id}",
                                  user_ids=[a.user_id] if a and a.user_id else None,
                                  roles=None if a and a.user_id else ["MANAGER"], object_type="opportunity",
                                  object_id=str(opp.id), event_id=ev.id, dedupe=f"info_expired:{ev.id}")
        notify.notify_customer(db, opp.customer_id, "InfoRequestExpired", title="A request has expired",
                               body=f"{inst.display_name}'s request on {opp.reference} has expired. They may contact "
                                    "you directly or ask again in WEZA.",
                               link="/c/status", object_type="info_request", object_id=ev.data.get("request_id"))
    else:
        a = db.get(Assignment, opp.id)
        notify.notify_institution(db, opp.institution_id, "InfoRequestFulfilled",
                                  title=f"Customer responded on {opp.reference}",
                                  body="The information you asked for is on the opportunity.",
                                  link=f"/institution/opportunities/{opp.id}",
                                  user_ids=[a.user_id] if a and a.user_id else None,
                                  roles=None if a and a.user_id else ["MANAGER"], object_type="opportunity",
                                  object_id=str(opp.id), event_id=ev.id, dedupe=f"info_fulfilled:{ev.id}")


@consumer("ops_alerts", ["OpportunityQualified", "InstitutionApplicationSubmitted", "IntegrityCaseOpened",
                         "DisputeOpened", "OpportunityRoutingFailed"])
def on_ops(db: Session, ev: OutboxEvent) -> None:
    if ev.event_type == "OpportunityQualified" and not ev.data.get("hold"):
        return
    titles = {"OpportunityQualified": f"Opportunity {ev.data.get('reference')} on hold for review",
              "InstitutionApplicationSubmitted": f"New institution application: {ev.data.get('name')}",
              "IntegrityCaseOpened": "Integrity case opened", "DisputeOpened": "New billing dispute",
              "OpportunityRoutingFailed": "Routing failure — customer data was not shared"}
    links = {"InstitutionApplicationSubmitted": "/admin/institutions", "DisputeOpened": "/admin/disputes",
             "IntegrityCaseOpened": "/admin/integrity"}
    notify.notify_weza_ops(db, ev.event_type, titles[ev.event_type], link=links.get(ev.event_type, "/admin/review"),
                           object_type=ev.aggregate_type, object_id=ev.aggregate_id)


@consumer("approval_requests", ["ProductSubmitted", "AppetiteSimulated"])
def on_approval_needed(db: Session, ev: OutboxEvent) -> None:
    if ev.institution_id is None:
        return
    if ev.event_type == "ProductSubmitted":
        notify.notify_institution(db, ev.institution_id, "ApprovalRequested",
                                  title=f"Product awaiting approval: {ev.data.get('name')} v{ev.data.get('version')}",
                                  link=f"/institution/products/{ev.aggregate_id}", priority="HIGH",
                                  roles=["INST_ADMIN", "EXECUTIVE", "CREDIT_RISK"], object_type="product",
                                  object_id=ev.aggregate_id, dedupe=f"approve:{ev.id}")
    else:
        notify.notify_institution(db, ev.institution_id, "ApprovalRequested",
                                  title=f"Appetite simulated (v{ev.data.get('version')}) — ready for approval",
                                  link=f"/institution/appetite/{ev.aggregate_id}", priority="NORMAL",
                                  roles=["INST_ADMIN", "EXECUTIVE", "CREDIT_RISK"], object_type="appetite",
                                  object_id=ev.aggregate_id, dedupe=f"approve:{ev.id}")


# ------------------------------------------------------------------ market clearing (G4) & waiting room (G5)


@consumer("market_clearing", ["AppetiteActivated", "AppetiteChanged", "AppetitePaused", "ProductActivated",
                              "ProductPaused", "InstitutionActivated", "InstitutionPaused", "InstitutionSuspended",
                              "KillSwitchChanged", "CustomerReactivated", "OpportunityExpired"])
def on_market_change(db: Session, ev: OutboxEvent) -> None:
    if ev.event_type in ("ProductPaused", "AppetitePaused", "InstitutionPaused", "InstitutionSuspended"):
        # Never leave a withdrawn product/mandate/institution in anyone's options (Skill §21)
        col = {"ProductPaused": Match.product_id, "AppetitePaused": Match.appetite_id}.get(ev.event_type, Match.institution_id)
        for m in db.execute(select(Match).where(col == uuid.UUID(ev.aggregate_id),
                                                Match.state.in_(["CANDIDATE", "ELIGIBLE", "RANKED", "PRESENTED",
                                                                 "SELECTED"]))).scalars():
            m.state, m.invalidated_reason = "INVALIDATED", f"{ev.event_type.lower()}"
    engine.clear_market(db, ev.event_type, trigger_ref=ev.aggregate_id)


@consumer("capacity_clearing", ["CapacityChanged"])
def on_capacity(db: Session, ev: OutboxEvent) -> None:
    if ev.data.get("to") in ("ACTIVE", "LIMITED", "FULL", "PAUSED"):
        engine.clear_market(db, "CapacityChanged", trigger_ref=ev.aggregate_id)


@consumer("fact_rematch", ["MaterialFactChanged"])
def on_fact_changed(db: Session, ev: OutboxEvent) -> None:
    cid = uuid.UUID(ev.aggregate_id)
    ids = list(db.execute(select(FinancialNeed.id).where(FinancialNeed.customer_id == cid,
                                                         FinancialNeed.status.in_(engine.ACTIVE_DEMAND))).scalars())
    if ids:
        engine.clear_market(db, "MaterialFactChanged", trigger_ref=ev.aggregate_id, need_ids=ids)


@consumer("waiting_room_notify", ["WaitingRoomMatchFound"])
def on_waiting_match(db: Session, ev: OutboxEvent) -> None:
    need = db.get(FinancialNeed, uuid.UUID(ev.aggregate_id))
    if need is None or need.customer_id is None:
        return
    notify.notify_customer(db, need.customer_id, "WaitingRoomMatchFound", title="A new option may fit your need",
                           body="Good news — a participating institution may now fit your financing request. Open WEZA "
                                "to review it. Nothing has been shared.", link="/start")
    if need.journey_id:
        from weza.domains.need.service import system_resume
        from weza.platform.models import GraphInstance
        gi = db.get(GraphInstance, need.journey_id)
        if gi and gi.current_node == "WAITING_ROOM":
            system_resume(db, need.journey_id, "_market_match")


@consumer("previews", ["NeedMatched"])
def on_need_matched_preview(db: Session, ev: OutboxEvent) -> None:
    """Level-2 Opportunity Preview (FSD §24, flag `marketplace.preview`). Allow-listed, non-identifiable."""
    if not flag(db, "marketplace.preview") or ev.data.get("readiness") not in ("READY_NOW", "ALMOST_READY"):
        return
    need = db.get(FinancialNeed, uuid.UUID(ev.aggregate_id))
    if need is None:
        return
    matches = db.execute(select(Match).where(Match.need_id == need.id, Match.state.in_(["RANKED", "PRESENTED"]))).scalars()
    for m in matches:
        if db.execute(select(Preview.id).where(Preview.match_id == m.id)).first():
            continue
        db.add(Preview(need_id=need.id, match_id=m.id, institution_id=m.institution_id,
                       payload=preview_payload(need, m), expires_at=utcnow() + timedelta(days=7)))


def preview_payload(need: FinancialNeed, m: Match) -> dict:
    """Allow-list serializer. Tested to never contain name, phone, NIN, email, address or documents."""
    amt = float(need.amount or 0)
    band = next(b for lo, b in [(1e9, "UGX 1B+"), (1e8, "UGX 100M–1B"), (5e7, "UGX 50–100M"), (1e7, "UGX 10–50M"),
                                (1e6, "UGX 1–10M"), (0, "Under UGX 1M")] if amt >= lo)
    score = m.score
    return {"customer_type": need.customer_type, "sector": need.sector, "region": need.region,
            "purpose_category": need.purpose_category, "amount_band": band,
            "match_band": "90+" if score >= 90 else "75–89" if score >= 75 else "60–74",
            "readiness": m.readiness}


# ------------------------------------------------------------------ audit hooks


@consumer("customer_activity", ["PhoneVerified"])
def on_phone_verified(db: Session, ev: OutboxEvent) -> None:
    need = db.get(FinancialNeed, uuid.UUID(ev.aggregate_id))
    if need and need.customer_id:
        c = db.get(Customer, need.customer_id)
        if c:
            c.last_activity_at = utcnow()


@consumer("outcome_audit", ["OutcomeReported"])
def on_outcome_audit(db: Session, ev: OutboxEvent) -> None:
    audit(db, SYSTEM, "opportunity.outcome_reported", "opportunity", ev.aggregate_id, institution_id=ev.institution_id,
          after={"state": ev.data.get("state"), "reason": ev.data.get("reason")})


def unread_count(db: Session, user_id) -> int:
    from sqlalchemy import func
    return db.execute(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == user_id, Notification.channel == "in_app", Notification.read_at.is_(None))).scalar_one()


@consumer("document_rematch", ["DocumentStored"])
def on_document_stored(db: Session, ev: OutboxEvent) -> None:
    """A newly stored document can turn ALMOST_READY options into READY ones — re-clear that customer's demand."""
    cid = uuid.UUID(ev.aggregate_id)
    ids = list(db.execute(select(FinancialNeed.id).where(FinancialNeed.customer_id == cid,
                                                         FinancialNeed.status.in_(engine.ACTIVE_DEMAND))).scalars())
    if ids:
        engine.clear_market(db, "DocumentStored", trigger_ref=ev.aggregate_id, need_ids=ids)


@consumer("identity_verify", ["IdentityCaptured"])
def on_identity_captured(db: Session, ev: OutboxEvent) -> None:
    """Check the captured NIN against the registry. A provider error raises, so the outbox retries with backoff;
    a superseded check (the customer changed their NIN/name again) is skipped."""
    from weza.domains.verification import service as verification
    from weza.domains.verification.models import IdentityCheck
    check = db.get(IdentityCheck, uuid.UUID(ev.data["check_id"])) if ev.data.get("check_id") else None
    if check is None or check.status not in ("PENDING", "ERROR"):
        return
    current = verification.latest(db, check.customer_id)
    if current is not None and current.id != check.id:
        return
    verification.run_check(db, check)


@consumer("identity_outcome", ["IdentityVerified", "IdentityVerificationFailed"])
def on_identity_outcome(db: Session, ev: OutboxEvent) -> None:
    """Verified identity can unlock options; a failed check is surfaced to the customer and to integrity review."""
    cid = uuid.UUID(ev.aggregate_id)
    if ev.event_type == "IdentityVerified":
        ids = list(db.execute(select(FinancialNeed.id).where(FinancialNeed.customer_id == cid,
                                                             FinancialNeed.status.in_(engine.ACTIVE_DEMAND))).scalars())
        if ids:
            engine.clear_market(db, "IdentityVerified", trigger_ref=ev.aggregate_id, need_ids=ids)
        return
    from weza.domains.integrity.service import add_review
    for opp in db.execute(select(Opportunity).where(Opportunity.customer_id == cid,
                                                    Opportunity.state.in_(list(opp_svc.OPEN_STATES)))).scalars():
        add_review(db, "IDENTITY_CHECK_FAILED", f"{opp.reference}: applicant identity check {ev.data.get('status')}",
                   "opportunity", opp.id, severity="HIGH", detail={"check_id": ev.data.get("check_id")},
                   dedupe_key=f"identity:{opp.id}:{ev.data.get('check_id')}")
    reason = ("doesn't match the name you gave" if ev.data.get("status") == "MISMATCH"
              else "wasn't found in the national register")
    notify.notify_customer(db, cid, "IdentityVerificationFailed", title="Please check your National ID",
                           body=f"The National ID number you entered {reason}. Please check it in WEZA — institutions "
                                "may not be able to proceed until it's confirmed.", link="/c/profile")


@consumer("info_answer_rematch", ["InfoRequestFulfilled"])
def on_info_answer(db: Session, ev: OutboxEvent) -> None:
    """An answer saved to the profile (first-time facts emit no MaterialFactChanged) can change readiness —
    re-clear that customer's demand. Document answers are already covered by DocumentStored."""
    if not ev.data.get("fact_saved") or not ev.data.get("customer_id"):
        return
    cid = uuid.UUID(ev.data["customer_id"])
    ids = list(db.execute(select(FinancialNeed.id).where(FinancialNeed.customer_id == cid,
                                                         FinancialNeed.status.in_(engine.ACTIVE_DEMAND))).scalars())
    if ids:
        engine.clear_market(db, "InfoRequestFulfilled", trigger_ref=ev.data.get("request_id"), need_ids=ids)


@consumer("readiness_notify", ["CustomerReadinessUpdated"])
def on_readiness(db: Session, ev: OutboxEvent) -> None:
    """ALMOST_READY → READY_NOW: tell the customer once a day per request. The Waiting Room has its own message."""
    if ev.data.get("previous") != "ALMOST_READY" or ev.data.get("readiness") != "READY_NOW":
        return
    if ev.data.get("trigger") in ("journey", "customer", "preferences"):
        return  # the customer is in the conversation and sees the options there
    need = db.get(FinancialNeed, uuid.UUID(ev.aggregate_id))
    if need is None or not need.customer_id or need.status == "WAITING":
        return
    from sqlalchemy import func
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    already = db.execute(select(func.count()).select_from(Notification).where(
        Notification.recipient_id == need.customer_id, Notification.event_type == "CustomerReadyNow",
        Notification.object_id == str(need.id), Notification.created_at >= midnight)).scalar_one()
    if already:
        return
    notify.notify_customer(db, need.customer_id, "CustomerReadyNow", title="Your request now has options",
                           body="Thanks for the extra information. Your request now fits at least one institution — "
                                "open WEZA to see your options.", link="/start", object_type="need",
                           object_id=str(need.id))
