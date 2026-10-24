"""Partner and campaign links with QR codes (BRD §5, TSD §73)."""

from urllib.parse import parse_qs, unquote, urlparse

import pytest
from sqlalchemy import select

from weza.config import get_settings
from weza.domains.commercial import referral
from weza.domains.notification.whatsapp_inbound import split_ref
from weza.domains.trust.models import AuditEvent
from weza.platform.db import session_scope
from weza.platform.errors import ValidationFailed


@pytest.fixture(autouse=True)
def number(monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_business_number", "+256 700 000 123")


def test_the_reference_has_four_slots_in_a_fixed_order():
    assert referral.reference("qr", "sacco-week", "kampala-sacco", "a1") == "(ref:qr~sacco-week~kampala-sacco~a1)"
    assert referral.reference(None, "only-campaign") == "(ref:~only-campaign~~)"


@pytest.mark.parametrize("bad", ["has space", "tilde~inside", "x" * 41, "semi;colon", "naïve", "a/b"])
def test_codes_that_could_break_the_format_are_refused(bad):
    with pytest.raises(ValidationFailed) as err:
        referral.reference(partner=bad)
    assert err.value.code == "INVALID_REFERRAL_CODE"


def test_at_least_one_code_is_needed():
    with pytest.raises(ValidationFailed) as err:
        referral.reference("", None, "  ", "")
    assert err.value.code == "REFERRAL_CODE_REQUIRED"


def test_a_link_carries_the_tag_and_the_inbound_parser_reads_it_back_exactly():
    link = referral.whatsapp_link("qr", "sacco-week", "kampala-sacco", "a1", text="I need a loan")
    url = urlparse(link)
    assert url.netloc == "wa.me" and url.path == "/256700000123"  # digits only, the number is never typed by a person
    first_message = unquote(parse_qs(url.query)["text"][0])
    text, attribution = split_ref(first_message)
    assert text == "I need a loan"
    assert attribution == {"src": "qr", "cmp": "sacco-week", "ptn": "kampala-sacco", "ref": "a1"}


def test_the_default_first_message_and_a_missing_number():
    assert split_ref(unquote(parse_qs(urlparse(referral.whatsapp_link(source="poster")).query)["text"][0]))[0] == "Hi"
    get_settings().whatsapp_business_number = None
    with pytest.raises(ValidationFailed) as err:
        referral.whatsapp_link(source="poster")
    assert err.value.code == "WHATSAPP_NUMBER_MISSING"


def test_the_qr_code_is_a_self_contained_svg_that_is_stable_for_a_link():
    link = referral.whatsapp_link("qr", partner="kcca")
    svg = referral.qr_svg(link)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>") and "<script" not in svg
    assert svg == referral.qr_svg(link) and svg != referral.qr_svg(referral.whatsapp_link("qr", partner="other"))


def test_only_commercial_staff_can_create_links_and_it_is_audited(client, as_user):
    path = "/api/v1/admin/referral-links"
    q = {"source": "qr", "campaign": "sacco-week", "partner": "kampala-sacco", "referral": "a1"}
    assert client.get(path, params=q).status_code == 401
    assert client.get(path, params=q, headers=as_user("ops@weza.demo")).status_code == 403
    r = client.get(path, params=q, headers=as_user("commercial@weza.demo"))
    assert r.status_code == 200
    body = r.json()
    assert body["reference"] == "(ref:qr~sacco-week~kampala-sacco~a1)" and body["qr_svg"].startswith("<svg")
    assert split_ref(unquote(parse_qs(urlparse(body["link"]).query)["text"][0]))[1]["ptn"] == "kampala-sacco"
    with session_scope() as db:
        event = db.execute(select(AuditEvent).where(AuditEvent.action == "referral_link.created",
                                                    AuditEvent.object_id == body["reference"])).scalars().first()
        assert event is not None and event.after == {"reference": body["reference"]}


def test_bad_input_gets_a_clear_422_not_a_broken_link(client, as_user):
    h = as_user("commercial@weza.demo")
    assert client.get("/api/v1/admin/referral-links", headers=h).json()["error"]["code"] == "REFERRAL_CODE_REQUIRED"
    r = client.get("/api/v1/admin/referral-links", params={"partner": "has space"}, headers=h)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REFERRAL_CODE"
