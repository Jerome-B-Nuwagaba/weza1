"""Connect the organisation's WhatsApp Business app number to WEZA with Embedded Signup (coexistence, Tech Provider).

Admin page → Facebook JS SDK `FB.login` (config_id, featureType=whatsapp_business_app_onboarding) → Meta returns a
one-time code (valid ~30 s) and, by window message, the WABA id → `connect()`:
  1. exchange the code for a business token (GET /oauth/access_token with the app ID + app secret);
  2. check which WABAs that token was granted (debug_token) and that the browser-reported WABA is one of them;
  3. subscribe this app to the WABA's webhooks (POST /<WABA_ID>/subscribed_apps);
  4. read the WABA's phone numbers with their coexistence status (is_on_biz_app, platform_type).
The phone number is NOT registered: a coexistence number is already registered (Meta), and registering is the
migration path. The business token is used only inside this call — never stored, logged or returned. Sending keeps
using WHATSAPP_TOKEN (system user); the admin copies the WABA and phone number IDs shown into the settings.
"""

import logging
import re

from sqlalchemy.orm import Session

from weza.config import get_settings
from weza.domains.notification.service import graph_call
from weza.domains.trust.service import audit
from weza.platform.context import Actor
from weza.platform.errors import ValidationFailed

log = logging.getLogger("weza.whatsapp")

# Embedded Signup launch options for onboarding an existing WhatsApp Business app number (Meta: "Onboard WhatsApp
# Business app users"; featureType in FB.login extras, sessionInfoVersion "3" for the window-message payload).
FEATURE_TYPE = "whatsapp_business_app_onboarding"
SESSION_INFO_VERSION = "3"
COEXISTENCE_FINISH = "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"
_ID = re.compile(r"^\d{5,32}$")


def launch_config() -> dict:
    """What the admin page needs to open Embedded Signup (app ID and configuration ID are public by design)."""
    s = get_settings()
    missing = s.whatsapp_embedded_signup_missing
    return {"ready": not missing, "missing": missing, "app_id": s.whatsapp_app_id if not missing else None,
            "config_id": s.whatsapp_embedded_signup_config_id if not missing else None,
            "graph_version": s.graph_api_version, "feature_type": FEATURE_TYPE,
            "session_info_version": SESSION_INFO_VERSION,
            "current": {"waba_id": s.whatsapp_business_account_id or None,
                        "phone_number_id": s.whatsapp_phone_number_id or None}}


def _meta_error(data: dict) -> dict:
    e = data.get("error") if isinstance(data.get("error"), dict) else {}
    return {"meta_code": e.get("code"), "meta_subcode": e.get("error_subcode")}


def _fail(message: str, code: str, status: int, data: dict) -> ValidationFailed:
    detail = {"http": status, **_meta_error(data)}
    log.warning("whatsapp_embedded_signup_failed", extra={"data": {"step": code, **detail}})
    return ValidationFailed(message, code=code, details=[{"field": "meta", "issue": str(detail)}])


def _mask(number) -> str | None:
    digits = re.sub(r"\D", "", str(number or ""))
    return f"…{digits[-3:]}" if digits else None


def connect(db: Session, actor: Actor, *, code: str, waba_id: str | None, event: str | None) -> dict:
    s = get_settings()
    if s.whatsapp_embedded_signup_missing:
        raise ValidationFailed("Embedded Signup is not configured: set " + ", ".join(s.whatsapp_embedded_signup_missing)
                               + ".", code="ES_NOT_CONFIGURED")
    if waba_id is not None and not _ID.match(waba_id):
        raise ValidationFailed("Invalid WhatsApp Business Account id.", code="ES_BAD_WABA")
    app_id, secret = s.whatsapp_app_id.strip(), s.whatsapp_app_secret.strip()

    # 1. code → business token (the code expires ~30 s after Meta issues it, and works once)
    status, data = graph_call("GET", "oauth/access_token",
                              params={"client_id": app_id, "client_secret": secret, "code": code})
    token = data.get("access_token") if status == 200 else None
    if not isinstance(token, str) or not token:
        raise _fail("Meta did not accept the sign-up code. It is valid for about 30 seconds and only once: please run "
                    "the sign-up again.", "ES_CODE_REJECTED", status, data)

    # 2. which WABAs did the business grant to this app?
    status, data = graph_call("GET", "debug_token", token=f"{app_id}|{secret}", params={"input_token": token})
    info = data.get("data") if status == 200 and isinstance(data.get("data"), dict) else {}
    scopes = info.get("granular_scopes") if isinstance(info.get("granular_scopes"), list) else []
    granted = sorted({str(t) for g in scopes if isinstance(g, dict) and g.get("scope") == "whatsapp_business_management"
                      for t in (g.get("target_ids") or [])})
    if waba_id and granted and waba_id not in granted:
        raise _fail("The WhatsApp Business Account reported by the sign-up window was not granted to this app.",
                    "ES_WABA_MISMATCH", status, {})
    waba = waba_id or (granted[0] if len(granted) == 1 else None)
    if not waba:
        raise _fail("Could not tell which WhatsApp Business Account was connected. Run the sign-up again and choose "
                    "one account.", "ES_WABA_UNKNOWN", status, data)

    # 3. deliver this WABA's webhooks (messages, account_update, …) to this app
    status, data = graph_call("POST", f"{waba}/subscribed_apps", token=token)
    subscribed = status == 200 and data.get("success") is True
    if not subscribed:
        log.warning("whatsapp_embedded_signup_subscribe_failed", extra={"data": {"http": status, **_meta_error(data)}})

    # 4. the WABA's numbers and their coexistence status (no registration: see module docstring)
    status, data = graph_call("GET", f"{waba}/phone_numbers", token=token, params={
        "fields": "id,display_phone_number,verified_name,platform_type,is_on_biz_app,code_verification_status"})
    want = re.sub(r"\D", "", s.whatsapp_business_number or "")
    numbers = [{"id": str(n.get("id")), "number": _mask(n.get("display_phone_number")),
                "verified_name": n.get("verified_name"), "platform_type": n.get("platform_type"),
                "is_on_biz_app": n.get("is_on_biz_app"), "verification": n.get("code_verification_status"),
                "is_business_number": bool(want) and re.sub(r"\D", "", str(n.get("display_phone_number"))) == want}
               for n in (data.get("data") if isinstance(data.get("data"), list) else [])
               if isinstance(n, dict) and n.get("id")] if status == 200 else []
    chosen = next((n for n in numbers if n["is_business_number"]), None) or next(
        (n for n in numbers if n["is_on_biz_app"]), None) or (numbers[0] if len(numbers) == 1 else None)
    coexistence = bool(chosen and chosen["is_on_biz_app"] and chosen["platform_type"] == "CLOUD_API")

    warnings = []
    if event and event != COEXISTENCE_FINISH:
        warnings.append(f"Meta reported {event[:60]}, not a WhatsApp Business app (coexistence) onboarding.")
    if not subscribed:
        warnings.append("Subscribing this app to the account's webhooks failed: incoming messages won't reach WEZA. "
                        "Run the sign-up again or subscribe in Meta (POST /<WABA_ID>/subscribed_apps).")
    if chosen is None:
        warnings.append("No phone number could be read for this account.")
    elif not coexistence:
        warnings.append("The number is not (yet) shown as shared between the WhatsApp Business app and Cloud API "
                        "(is_on_biz_app=true, platform_type=CLOUD_API). Do not register it: check again in a few "
                        "minutes with scripts/whatsapp_account_check.py.")
    result = {"waba_id": waba, "subscribed": subscribed, "coexistence": coexistence, "event": event,
              "phone_numbers": numbers, "warnings": warnings,
              "settings": {"WHATSAPP_BUSINESS_ACCOUNT_ID": waba,
                           "WHATSAPP_PHONE_NUMBER_ID": chosen["id"] if chosen else None},
              "settings_already_match": bool(chosen) and s.whatsapp_business_account_id == waba
              and s.whatsapp_phone_number_id == chosen["id"]}
    audit(db, actor, "whatsapp.embedded_signup", "whatsapp_account", waba,
          after={"subscribed": subscribed, "coexistence": coexistence, "event": event,
                 "phone_number_ids": [n["id"] for n in numbers]})
    log.info("whatsapp_embedded_signup_done", extra={"data": {"subscribed": subscribed, "coexistence": coexistence,
                                                              "numbers": len(numbers)}})
    return result
