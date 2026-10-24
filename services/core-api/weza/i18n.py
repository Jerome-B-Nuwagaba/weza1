"""Localisation foundation (TSD §72): language is separate from business logic.

Customer-facing wording lives in catalogue files, one per language, under weza/locales/<language>.json, as flat
"key": "text with {placeholders}". Code asks for a key (`t("id.request", "lg")`); it never builds wording out of English
fragments, so adding a language means adding a file, not changing logic.

Supported language codes (TSD §72): en English, lg Luganda, rw Kinyarwanda, sw Swahili, fr French. Only English is
written today. A key missing from a language, or an unknown language, falls back to English, so a half-translated language
never breaks a conversation.

What is deliberately NOT in a catalogue: approved legal and consent text. Those are versioned templates (consent
template versions, the credit-bureau consent wording) whose exact words are approved and hashed; a translation of them is
a new approved version, never a catalogue entry and never an AI translation (TSD §72). tests/test_i18n.py enforces this.
"""

import json
from functools import lru_cache
from pathlib import Path

LANGUAGES = ("en", "lg", "rw", "sw", "fr")
DEFAULT = "en"
LOCALES = Path(__file__).parent / "locales"


@lru_cache
def catalogue(lang: str) -> dict[str, str]:
    path = LOCALES / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def language(code: str | None) -> str:
    """A supported language code, or English."""
    return code if code in LANGUAGES else DEFAULT


def t(key: str, lang: str | None = None, **values) -> str:
    """The wording for `key` in `lang` (English when that language lacks it), with placeholders filled in.
    An unknown key is a programming error and raises, so a typo cannot reach a customer as a blank message."""
    text = catalogue(language(lang)).get(key)
    if text is None:
        text = catalogue(DEFAULT)[key]
    return text.format(**values) if values else text
