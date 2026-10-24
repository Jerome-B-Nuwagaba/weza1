"""Demo — the customer credit-marketplace journey, step by step, to a Qualified Opportunity at Demo Bank.

This is the safe development entry point for the customer journey. It drives the real journey graph, the real
matching engine, the real consent service, the real opportunity saga and the real routing through the same web
channel the browser client uses (`POST /api/v1/journeys`). Nothing is mocked: the only development convenience is
the one the web client already has — the OTP code is printed instead of being sent by SMS.

The WhatsApp channel is a live Meta integration owned elsewhere and is not used or touched here.

Usage:
    python scripts/demo_marketplace_journey.py
        # starts a throwaway local PostgreSQL, migrates, seeds, creates Demo Bank and runs the journey
    DATABASE_URL=postgresql://... python scripts/demo_marketplace_journey.py
        # runs against an existing database (the same one the API is using)
"""

import os
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault("RUN_WORKER_INPROCESS", "false")
os.environ.setdefault("OTP_DELIVERY", "display")  # the code is shown to the caller, never sent by SMS
os.environ.setdefault("ENV", "dev")
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.pop("ANTHROPIC_API_KEY", None)  # the deterministic path, so the demo is reproducible

PHONE = f"077{random.randint(100, 999)}{random.randint(1000, 9999)}"  # a fresh customer every run
NEED_TEXT = "I need UGX 30 million to expand my pharmacy"
PROFILE = {
    "identity.full_name": "Grace Nakato",
    "identity.nin": "skip",  # no National ID: the bureau check is Just-In-Time, at the lender's stage
    "business.name": "Nakato Pharmacy",
    "business.sector": "health_pharmacy",
    "business.district": "Kampala",
    "business.age_months": "4 years",
    "business.monthly_turnover": "12 million",
    "business.registered": "yes",
    "finance.monthly_repayments": "0",
    "need.tenor_months": "24 months",
}


# ------------------------------------------------------------------ setup


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    import pgserver

    srv = pgserver.get_server(str(ROOT / ".pgdata"), cleanup_mode=None)
    if "weza" not in srv.psql("SELECT datname FROM pg_database;").split():
        srv.psql("CREATE DATABASE weza;")
    return srv.get_uri().rsplit("/", 1)[0] + "/weza"


def _prepare_database(url: str) -> None:
    env = {**os.environ, "DATABASE_URL": url}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
    subprocess.run([sys.executable, "-m", "weza.seed"], cwd=ROOT, env=env, check=False)


def _demo_bank() -> dict:
    """Demo Bank: an ACTIVE institution with one ACTIVE product and one ACTIVE mandate, built by the real services."""
    from weza.platform.db import session_scope
    from weza.seed import seed_demo_bank

    with session_scope() as db:
        state = seed_demo_bank(db)
        return {"id": str(state["inst"].id), "name": state["inst"].display_name}


# ------------------------------------------------------------------ output helpers


def step(n: int, title: str) -> None:
    print(f"\n{'=' * 78}\nSTEP {n} - {title}\n{'=' * 78}")


def say(text: str) -> None:
    print(f"  WEZA > {text}")


def me(text: str) -> None:
    print(f"  CUSTOMER > {text}")


def field(label: str, value) -> None:
    print(f"    {label:<22} {value}")


# ------------------------------------------------------------------ the journey driver


class Journey:
    """Drives the customer conversation exactly as the web client does."""

    def __init__(self, client, text: str):
        self.client = client
        r = client.post("/api/v1/journeys", json={"channel": "web", "text": text, "src": "demo"})
        r.raise_for_status()
        self.data = r.json()
        self.id = self.data["journey_id"]
        self.headers = {"X-Journey-Token": self.data["token"]}
        self.session_token = None
        for s in self.cards("session"):
            self.session_token = s["token"]

    @property
    def customer_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.session_token}"}

    @property
    def node(self) -> str:
        return self.data["node"]

    def cards(self, kind: str) -> list[dict]:
        return [o["data"] for o in self.data.get("outputs", []) if o.get("type") == "card" and o.get("card") == kind]

    def texts(self) -> list[str]:
        return [o["text"] for o in self.data.get("outputs", []) if o.get("type") == "text"]

    def send(self, text: str | None = None, **payload) -> "Journey":
        body = {"text": text, **payload} if text is not None else payload
        r = self.client.post(f"/api/v1/journeys/{self.id}/messages", json=body, headers=self.headers)
        r.raise_for_status()
        self.data = r.json()
        for s in self.cards("session"):
            self.session_token = s["token"]
        return self

    def verify(self, phone: str) -> "Journey":
        self.send(phone)
        codes = self.cards("otp_input")
        if not codes:
            raise RuntimeError(f"the phone number was not accepted: {' '.join(self.texts())}")
        code = codes[0]["dev_code"]
        say(f"(development mode: the code {code} is shown instead of being sent by SMS)")
        return self.send(code)

    def answer_profile(self) -> "Journey":
        for _ in range(30):
            if self.node != "ASK_PROFILE":
                return self
            question = self.cards("question")[0]
            answer = PROFILE[question["key"]]
            say(self.texts()[-1] if self.texts() else question["key"])
            me(answer)
            self.send(answer)
        raise RuntimeError("the profile did not complete")


# ------------------------------------------------------------------ the demo


def main() -> int:
    url = _database_url()
    os.environ["DATABASE_URL"] = url
    _prepare_database(url)

    import logging

    from fastapi.testclient import TestClient

    logging.getLogger("weza.api").setLevel(logging.WARNING)  # keep the demo output readable
    from weza.main import create_app
    from weza.platform.db import reset_engine

    for name in ("weza.api", "weza.notify", "weza.worker", "weza.events", "weza.platform.events"):
        logging.getLogger(name).setLevel(logging.WARNING)
    reset_engine(url)
    bank = _demo_bank()
    app = create_app(start_worker=False)

    with TestClient(app) as client:
        j = Journey(client, NEED_TEXT)

        step(1, "The customer states what they need")
        me(NEED_TEXT)
        for t in j.texts():
            say(t)
        for card in j.cards("understanding"):
            amount = card.get("amount_value")
            field("amount", f"UGX {amount:,}" if amount else card.get("amount"))
            field("purpose", card.get("purpose"))
            field("customer type", card.get("customer_type"))
            field("sector", card.get("sector"))

        step(2, "WEZA reads it back — the customer confirms before anything happens")
        j.send(action="confirm")
        for t in j.texts():
            say(t)

        step(3, "The phone number is verified")
        say("WEZA asks for a mobile number and sends a 6-digit code.")
        j.verify(PHONE)
        for t in j.texts():
            say(t)

        step(4, "The customer completes the minimum profile")
        j.answer_profile()
        for t in j.texts():
            say(t)

        step(5, "WEZA checks the active products and mandates, and scores the fit")
        options = j.cards("options")[0]["options"]
        for o in options:
            print(f"  • {o['institution']} — {o['product']}")
            field("match score", f"{o['score']} / 100 (readiness: {o['readiness']})")
            field("components", o["components"])
            field("why", "; ".join(o["why"]) or "—")
            if o["outstanding"]:
                field("still needed", "; ".join(o["outstanding"]))
        for t in j.texts():
            say(t)

        step(6, "The customer chooses Demo Bank")
        demo = next(o for o in options if o["institution"] == bank["name"])
        me(f"Choose {bank['name']} — {demo['product']} (match {demo['score']}/100)")
        j.send(action="select", value=demo["match_id"])
        consent = j.cards("consent")[0]
        for t in j.texts():
            say(t)
        print("\n  The consent the customer is shown:")
        print(f"    {consent['text']}")
        field("version", consent["version"])
        field("institution", consent["institution"])

        step(7, "The customer gives explicit, institution-specific consent")
        me("I agree — share with " + bank["name"])
        j.send(action="agree", value=consent["template_id"])
        for t in j.texts():
            say(t)
        print(f"\n  Journey node after the share: {j.node} (the bureau check happens later, at the lender's stage)")

        step(8, "WEZA creates the Qualified Opportunity and routes it to Demo Bank")
        submitted = j.cards("submitted")[0]
        field("reference", submitted["reference"])
        field("institution", submitted["institution"])
        field("expected contact", f"within {round(submitted['expected_contact_hours'])} hours")
        drain()
        _show_outcome(submitted["reference"], bank)

    print("\nDemo complete. The customer can now track the request at /requests, and Demo Bank sees it in its "
          "opportunity feed.\n")
    return 0


def _show_outcome(reference: str, bank: dict) -> None:
    from sqlalchemy import select

    from weza.domains.appetite.models import Appetite
    from weza.domains.consent.models import Consent, CrbCheck
    from weza.domains.identity.models import User
    from weza.domains.opportunity.models import Assignment, Opportunity
    from weza.domains.trust.models import AuditEvent
    from weza.platform.db import session_scope

    with session_scope() as db:
        opp = db.execute(select(Opportunity).where(Opportunity.reference == reference)).scalar_one()
        consent = db.get(Consent, opp.consent_id)
        assignment = db.get(Assignment, opp.id)
        owner = db.get(User, assignment.user_id) if assignment and assignment.user_id else None
        mandate = db.get(Appetite, opp.appetite_id) if opp.appetite_id else None
        field("state", opp.state)
        field("match score", opp.match_score)
        field("product shown", (opp.snapshot or {}).get("product_version", {}).get("name"))
        field("mandate", mandate.name if mandate else "—")
        field("consent", f"{consent.status} (v{consent.template_version}, categories: {', '.join(consent.data_categories)})")
        field("assigned to", f"{owner.full_name} <{owner.email}>" if owner else "Unassigned queue")
        field("bureau calls", len(db.execute(select(CrbCheck).where(
            CrbCheck.customer_id == opp.customer_id)).scalars().all()))
        print("\n  Audit trail:")
        for row in db.execute(select(AuditEvent).where(
                AuditEvent.object_type.in_(["opportunity", "consent"]),
                AuditEvent.object_id.in_([str(opp.id), str(consent.id)])).order_by(AuditEvent.at)).scalars():
            field(row.action, f"{row.actor_display} · {row.object_type}")


def drain() -> None:
    """Deliver the queued events (assignment, notification, billing) so the demo shows the final state."""
    from weza.platform.events import drain as _drain

    _drain()


if __name__ == "__main__":
    raise SystemExit(main())
