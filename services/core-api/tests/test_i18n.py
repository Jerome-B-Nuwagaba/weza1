"""Localisation foundation (TSD §72): language separated from logic, English fallback, approved legal text kept out."""

import json
import re
import string
from pathlib import Path

import pytest

from tests.test_whatsapp_channel import (  # noqa: F401 — fixtures are picked up by name
    fake_phone,
    http,
    journeys_for,
    out_messages,
    text_msg,
    wa_inbound,
)
from weza import i18n
from weza.domains.consent import crb_service
from weza.domains.customer import service as customer_svc
from weza.domains.customer.models import Preference
from weza.platform.db import session_scope

ROOT = Path(__file__).resolve().parents[1] / "weza"
# keys built from a variable in the code ("id." + field), so a plain scan cannot see them
DYNAMIC = {"id.date_of_birth", "id.expiry_date"}


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def english() -> dict[str, str]:
    return json.loads((ROOT / "locales" / "en.json").read_text(encoding="utf-8"))


@pytest.fixture()
def locales(tmp_path, monkeypatch):
    """A scratch locales folder with an invented 'lg' (Luganda) catalogue, so the real files are never touched."""
    monkeypatch.setattr(i18n, "LOCALES", tmp_path)
    i18n.catalogue.cache_clear()
    (tmp_path / "en.json").write_text(json.dumps(english()), encoding="utf-8")
    yield tmp_path
    i18n.catalogue.cache_clear()


def test_english_wording_comes_back_with_its_placeholders_filled():
    assert i18n.t("prompt.amount") == "How much financing do you need?"
    assert i18n.t("payout.example", example="0772 123 456") == "e.g. 0772 123 456"
    assert "{institution}" not in i18n.t("payout.ask", "en", institution="Lakeside Bank")


def test_an_unknown_language_or_a_missing_translation_falls_back_to_english(locales):
    assert i18n.t("prompt.amount", "klingon") == i18n.t("prompt.amount", None) == "How much financing do you need?"
    (locales / "lg.json").write_text(json.dumps({"prompt.amount": "[lg] How much?"}), encoding="utf-8")
    i18n.catalogue.cache_clear()
    assert i18n.t("prompt.amount", "lg") == "[lg] How much?"
    assert i18n.t("prompt.greet", "lg") == english()["prompt.greet"]  # not translated yet: English, never blank


def test_an_unknown_key_raises_instead_of_reaching_a_customer_as_a_blank_message():
    with pytest.raises(KeyError):
        i18n.t("no.such.key")


def test_every_key_the_code_asks_for_exists_and_no_catalogue_entry_is_orphaned():
    used = set()
    for f in ROOT.rglob("*.py"):
        src = f.read_text(encoding="utf-8")
        used |= set(re.findall(r"\b_t\(\s*st,\s*\"([a-z_.]+)\"", src))
        used |= set(re.findall(r"\bi18n\.t\(\s*\"([a-z_.]+)\"", src))
        used |= set(re.findall(r"\"(prompt\.[a-z_]+|payout\.[a-z_]+)\"", src))  # keys held in dicts and variables
    catalogue = set(english())
    assert used <= catalogue, f"keys used in code but missing from en.json: {sorted(used - catalogue)}"
    assert catalogue - used <= DYNAMIC, f"entries nothing uses: {sorted(catalogue - used - DYNAMIC)}"


def test_every_english_text_formats_cleanly_with_its_own_placeholders():
    for text in english().values():
        text.format(**{p: "x" for p in placeholders(text)})  # raises on a stray brace or a malformed field


def test_a_translation_can_only_translate_what_english_has_and_must_keep_every_placeholder():
    """Real catalogues, whatever languages exist now or later: no invented keys, no dropped or renamed placeholders (a
    dropped {institution} would send a customer a message that no longer says who their data goes to)."""
    en = english()
    for path in (ROOT / "locales").glob("*.json"):
        if path.stem == "en":
            continue
        assert path.stem in i18n.LANGUAGES, f"{path.name} is not a supported language code"
        for key, text in json.loads(path.read_text(encoding="utf-8")).items():
            assert key in en, f"{path.name}: {key} has no English original"
            assert placeholders(text) == placeholders(en[key]), f"{path.name}: placeholders of {key} differ from English"


def test_approved_legal_and_consent_wording_is_never_in_a_catalogue():
    assert not [k for k in english() if k.startswith(("consent.", "legal.", "crb."))]
    marker = crb_service.CONSENT_TEXT.split("{institution}")[0]
    assert not [k for k, v in english().items() if marker.strip() in v]  # the credit-bureau consent text stays a versioned template


def test_a_customer_with_a_saved_language_is_spoken_to_in_it(client, locales, wa_inbound):
    (locales / "lg.json").write_text(json.dumps({
        "offtopic.welcome": "[lg] Welcome to WEZA. Financing only. {reprompt}",
        "prompt.greet": "[lg] Tell me what you need financing for."}), encoding="utf-8")
    i18n.catalogue.cache_clear()
    phone = fake_phone()
    with session_scope() as db:
        customer, _ = customer_svc.get_or_create_by_phone(db, "+" + phone)
        db.get(Preference, customer.id).language = "lg"
    text_msg(client, phone, "what is the weather in Kampala today?")
    last = [m for m in out_messages(phone) if m.channel == "whatsapp"][-1].body
    assert last == "[lg] Welcome to WEZA. Financing only. [lg] Tell me what you need financing for."
    assert journeys_for(phone)


def test_a_customer_with_no_saved_language_gets_english(client, wa_inbound):
    phone = fake_phone()
    text_msg(client, phone, "what is the weather in Kampala today?")
    last = [m for m in out_messages(phone) if m.channel == "whatsapp"][-1].body
    assert last.startswith("Welcome to WEZA. I can only help with financing requests")
