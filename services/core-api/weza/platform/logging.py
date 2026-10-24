"""Structured JSON logging with classification-aware redaction (TSD §66)."""

import json
import logging
import re
import sys
from datetime import UTC, datetime

from weza.platform import classification
from weza.platform.context import correlation_id_var

# Broad fragments kept from before (they catch names like "first_name" or "contact_phone"), plus every field the central
# classification (TSD §49) rates PERSONAL or HIGHLY_SENSITIVE, so a newly classified field is redacted without a code change.
_GENERIC = ("phone", "nin", "otp", "code", "password", "secret", "token", "name", "email", "address", "document", "dob")
SENSITIVE_KEYS = re.compile("(" + "|".join(sorted({*_GENERIC, *classification.redacted_key_fragments()})) + ")", re.I)
PHONE_RE = re.compile(r"\+?\d[\d\s-]{8,14}\d")
NIN_RE = re.compile(r"\b[CA][MF][A-Z0-9]{12}\b")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


def redact_text(text: str) -> str:
    text = NIN_RE.sub("[NIN]", text)
    text = EMAIL_RE.sub("[EMAIL]", text)
    return PHONE_RE.sub("[PHONE]", text)


def redact(value):
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if SENSITIVE_KEYS.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact_text(record.getMessage()),
            "correlation_id": correlation_id_var.get() or None,
        }
        extra = getattr(record, "data", None)
        if extra:
            payload["data"] = redact(extra)
        if record.exc_info:
            payload["exc"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    logging.getLogger("httpx2").setLevel("WARNING")
    logging.getLogger("httpx").setLevel("WARNING")
