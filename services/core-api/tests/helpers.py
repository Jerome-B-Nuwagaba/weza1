"""Shared test helpers."""

import uuid


def idem(headers: dict) -> dict:
    return {**headers, "Idempotency-Key": uuid.uuid4().hex}


def routed_to_lakeside(journey, phone: str):
    """Run a fresh SME customer through to a Lakeside opportunity; return (journey, opp_id, assigned officer email)."""
    from sqlalchemy import select

    from weza.domains.identity.models import User
    from weza.domains.opportunity.models import Assignment, Opportunity
    from weza.platform.db import session_scope
    from weza.platform.events import drain
    j = journey("I need UGX 20 million to buy stock for my pharmacy")
    j.send(action="confirm")
    j.verify(phone)
    j.answer_profile({**SME_ANSWERS, "identity.nin": f"CM{phone}AB"})
    opt = next(o for o in j.cards("options")[0]["options"] if o["institution"] == "Lakeside Bank")
    j.send(action="select", value=opt["match_id"])
    j.send(action="agree", value=j.cards("consent")[0]["template_id"])
    ref = j.cards("submitted")[0]["reference"]
    drain()
    with session_scope() as db:
        o = db.execute(select(Opportunity).where(Opportunity.reference == ref)).scalar_one()
        owner = db.get(User, db.get(Assignment, o.id).user_id).email
        return j, str(o.id), owner


def login(client, email: str, password: str = "WezaDemo!2026") -> dict:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


class Journey:
    """Drives the customer conversation exactly as the web client does."""

    def __init__(self, client, text: str | None = None, **attribution):
        self.client = client
        r = client.post("/api/v1/journeys", json={"channel": "web", "text": text, **attribution})
        assert r.status_code == 200, r.text
        self.data = r.json()
        self.id = self.data["journey_id"]
        self.headers = {"X-Journey-Token": self.data["token"]}
        self.session_token = None

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
        assert r.status_code == 200, r.text
        self.data = r.json()
        for s in self.cards("session"):
            self.session_token = s["token"]
        return self

    @property
    def customer_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.session_token}"}

    def verify(self, phone: str) -> "Journey":
        assert self.node == "VERIFY_PHONE", self.node
        self.send(phone)
        code = self.cards("otp_input")[0]["dev_code"]
        return self.send(code)

    def answer_profile(self, answers: dict[str, str], max_steps: int = 30) -> "Journey":
        for _ in range(max_steps):
            if self.node != "ASK_PROFILE":
                return self
            q = self.cards("question")[0]
            assert q["key"] in answers, f"unexpected question {q['key']}"
            self.send(answers[q["key"]])
        raise AssertionError("profile did not complete")


SME_ANSWERS = {
    "identity.full_name": "Grace Nakato", "identity.nin": "CM1234567890AB",
    "business.name": "Nakato Pharmacy", "business.sector": "health_pharmacy", "business.district": "Kampala",
    "business.age_months": "4 years", "business.monthly_turnover": "12 million", "business.registered": "yes",
    "finance.monthly_repayments": "0", "need.tenor_months": "24 months",
}
