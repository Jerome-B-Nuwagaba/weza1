"""Demo — the institution-officer experience of a routed opportunity, end to end.

Runs the whole path in one go, with nothing faked:

    demo customer → phone verified → matched → consented → routed to Journey Demo Bank
    → Journey Demo Bank's officer sees it in their queue, reads what was shared and why,
      records the statuses, asks for more information, and reports the outcome.

The institution decides; WEZA records. Nothing here approves a loan or moves money.

Usage:
    python scripts/demo_opportunity_workspace.py
        # starts a throwaway local PostgreSQL, migrates, seeds, creates Journey Demo Bank and runs the demo
    DATABASE_URL=postgresql://... python scripts/demo_opportunity_workspace.py
        # runs against an existing database
"""

import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("RUN_WORKER_INPROCESS", "false")
os.environ.setdefault("OTP_DELIVERY", "display")  # the code is shown to the caller, never sent by SMS
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.pop("ANTHROPIC_API_KEY", None)  # the deterministic path, so the demo is reproducible

PHONE = f"077{random.randint(100, 999)}{random.randint(1000, 9999)}"  # a fresh customer every run
NEED_TEXT = "I need UGX 30 million to expand my pharmacy"
OFFICER_EMAIL = "officer@demo.bank"
OFFICER_PASSWORD = "WezaDemo!2026"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


# ------------------------------------------------------------------ output helpers


def step(n: int, title: str) -> None:
    print(f"\n{'=' * 78}\nSTEP {n} - {title}\n{'=' * 78}")


def say(text: str) -> None:
    print(f"  WEZA > {text}")


def me(text: str) -> None:
    print(f"  CUSTOMER > {text}")


def officer(text: str) -> None:
    print(f"  OFFICER > {text}")


def field(label: str, value) -> None:
    print(f"    {label:<24} {value}")


# ------------------------------------------------------------------ the demo


def main() -> int:
    from demo_marketplace_journey import (  # noqa: E402  (the same journey the customer demo drives)
        Journey, _database_url, _demo_bank, _prepare_database, drain,
    )

    url = _database_url()
    os.environ["DATABASE_URL"] = url
    _prepare_database(url)

    import logging

    from fastapi.testclient import TestClient

    from weza.main import create_app
    from weza.platform.db import reset_engine

    for name in ("weza.api", "weza.notify", "weza.worker", "weza.events", "weza.platform.events"):
        logging.getLogger(name).setLevel(logging.WARNING)
    reset_engine(url)
    bank = _demo_bank()
    app = create_app(start_worker=False)

    with TestClient(app) as client:
        # ---------------------------------------------------------- the customer journey
        step(1, "The customer states what they need, and is verified")
        j = Journey(client, NEED_TEXT)
        me(NEED_TEXT)
        for t in j.texts():
            say(t)
        j.send(action="confirm")
        j.verify(PHONE)
        for t in j.texts():
            say(t)
        j.answer_profile()
        say("Minimum profile complete (customer type, amount, purpose, sector, location, business age).")

        step(2, "WEZA matches the customer and the customer consents to share with Journey Demo Bank")
        options = j.cards("options")[0]["options"]
        for o in options:
            print(f"  • {o['institution']} — {o['product']} (match {o['score']}/100, readiness {o['readiness']})")
        demo = next(o for o in options if o["institution"] == bank["name"])
        me(f"Choose {bank['name']} — {demo['product']}")
        j.send(action="select", value=demo["match_id"])
        consent = j.cards("consent")[0]
        say(consent["text"])
        me("I agree — share with " + bank["name"])
        j.send(action="agree", value=consent["template_id"])
        reference = j.cards("submitted")[0]["reference"]
        for t in j.texts():
            say(t)
        drain()

        # ---------------------------------------------------------- the officer signs in
        step(3, "Journey Demo Bank's officer signs in")
        r = client.post("/api/v1/auth/login", json={"email": OFFICER_EMAIL, "password": OFFICER_PASSWORD})
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        me_ = client.get("/api/v1/auth/me", headers=h).json()
        field("signed in", f"{me_['full_name']} <{me_['email']}>")
        field("roles", ", ".join(me_["role_labels"][x] for x in me_["roles"]))
        field("institution", f"{me_['institution']['name']} ({me_['institution']['status']})")

        step(4, "The officer's queue — only their own institution's work")
        day = client.get("/api/v1/inst/my-day", headers=h).json()
        for key, items in day["sections"].items():
            for i in items:
                print(f"  • [{key}] {i['reference']} — UGX {i['amount']:,.0f} · match {i['match_score']} · "
                      f"owner {i['owner']} · {i['next_action']}")
        assert any(i["reference"] == reference for i in day["sections"]["new"]), "the routed opportunity is not in the queue"

        step(5, "The officer opens it — what was shared, why it matched, and under what consent")
        oid = _opp_id(reference)
        view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
        field("reference", view["reference"])
        field("requested amount", f"UGX {view['amount']:,.0f}")
        field("purpose", view["need"])
        field("match score", f"{view['match_score']} / 100")
        field("quality / readiness score", view["quality_score"])
        field("why it matched", "; ".join(view["why_matched"]) or "—")
        field("near miss", "; ".join(view["near_miss"]) or "—")
        field("consent", f"{view['consent']['status']} (v{view['consent']['version']}, "
                         f"{', '.join(view['consent']['categories'])})")
        field("customer", view["customer"]["fields"].get("full_name"))
        field("documents shared", len(view["customer"].get("documents") or []))
        field("status", view["state"])
        print("\n  The officer's status ladder:")
        for s in view["status_ladder"]:
            mark = "->" if s["current"] else ("   " if s["reached"] else "   ")
            print(f"    {mark} {s['label']}")

        step(6, "The officer records the statuses")
        officer("Mark contacted")
        view = _status(client, h, oid, "CONTACTED", "Called the customer and introduced the offer.")
        field("status", view["state"])
        field("next action", view["next_states"])

        officer("More information requested — ask the customer for 6 months of bank statements")
        view = _request_info(client, h, oid)
        field("status", view["state"])
        field("asked for", view["info_requests"][0]["doc_label"])
        field("waiting for the customer", view["awaiting_customer"])
        view = _status(client, h, oid, "INFORMATION_REQUESTED", "Asked for 6 months of bank statements.")
        field("status", view["state"])
        field("next action", view["next_states"])

        # The customer answers, and the document becomes available to the officer
        drain()
        mine = client.get("/api/v1/me/info-requests", headers=j.customer_headers).json()
        doc = client.post("/api/v1/me/documents", headers=j.customer_headers, data={"doc_type": "bank_statement"},
                          files={"file": ("statement.pdf", PDF, "application/pdf")}).json()
        client.post(f"/api/v1/me/info-requests/{mine['requests'][0]['id']}/respond", headers=j.customer_headers,
                    json={"document_id": doc["id"]})
        drain()
        view = client.get(f"/api/v1/inst/opportunities/{oid}", headers=h).json()
        field("documents now available", ", ".join(d["doc_type"] for d in view["customer"].get("documents") or []))

        officer("Internal note for the team")
        r = client.post(f"/api/v1/inst/opportunities/{oid}/note", headers=h,
                        json={"note": "Credit file opened; the customer will bring the original statements."})
        view = r.json()
        field("note saved", "yes — visible to the institution only")

        officer("Send for institution review")
        view = _status(client, h, oid, "SUBMITTED_TO_INSTITUTION", "File complete — with the credit committee.")
        field("status", view["state"])

        step(7, "The officer reports the outcome — the institution's own decision")
        officer("Report approved")
        view = _outcome(client, h, oid, {"state": "REPORTED_APPROVED", "approved_amount": 30_000_000,
                                         "tenor_months": 24})
        field("status", view["state"])
        field("reported", view["outcomes"][-1]["label"])
        field("approved amount", f"UGX {view['outcomes'][-1]['approved_amount']:,.0f}")
        officer("Report disbursed")
        view = _outcome(client, h, oid, {"state": "REPORTED_DISBURSED", "disbursed_amount": 30_000_000,
                                         "disbursed_on": "2026-10-30"})
        field("status", view["state"])
        field("reported", view["outcomes"][-1]["label"])
        print("    (amount and date only — WEZA has no destination to pay, and it never moves money)")

        step(8, "The audit trail — every status change, the consent and the routing")
        _audit(reference, oid)

        step(9, "What the customer sees")
        needs = client.get("/api/v1/me/needs", headers=j.customer_headers).json()["needs"]
        mine_opp = next(o for o in needs[0]["opportunities"] if o["reference"] == reference)
        field("status", mine_opp["status_label"])
        for t in mine_opp["timeline"]:
            field("timeline", f"{t['label']}")
        field("internal note visible?", "no — notes never reach the customer")

    print("\nDemo complete.\n")
    return 0


# ------------------------------------------------------------------ helpers


def _opp_id(reference: str):
    from sqlalchemy import select

    from weza.domains.opportunity.models import Opportunity
    from weza.platform.db import session_scope

    with session_scope() as db:
        return db.execute(select(Opportunity).where(Opportunity.reference == reference)).scalar_one().id


def _status(client, h, oid, state: str, note: str) -> dict:
    r = client.post(f"/api/v1/inst/opportunities/{oid}/status", headers={**h, "Idempotency-Key": os.urandom(8).hex()},
                    json={"state": state, "note": note})
    r.raise_for_status()
    return r.json()


def _request_info(client, h, oid) -> dict:
    r = client.post(f"/api/v1/inst/opportunities/{oid}/info-requests",
                    headers={**h, "Idempotency-Key": os.urandom(8).hex()},
                    json={"kind": "DOCUMENT", "doc_type": "bank_statement",
                          "message": "Please share 6 months of bank statements."})
    r.raise_for_status()
    return r.json()


def _outcome(client, h, oid, body: dict) -> dict:
    r = client.post(f"/api/v1/inst/opportunities/{oid}/outcome",
                    headers={**h, "Idempotency-Key": os.urandom(8).hex()}, json=body)
    r.raise_for_status()
    return r.json()


def _audit(reference: str, oid) -> None:
    from sqlalchemy import select

    from weza.domains.trust.models import AuditEvent
    from weza.platform.db import session_scope

    with session_scope() as db:
        rows = db.execute(select(AuditEvent).where(
            AuditEvent.object_type == "opportunity", AuditEvent.object_id == str(oid)).order_by(AuditEvent.at)).scalars()
        for r in rows:
            after = (r.after or {}).get("state") or (r.after or {}).get("note") or ""
            field(r.action, f"{r.actor_display} · {after}")


if __name__ == "__main__":
    raise SystemExit(main())
