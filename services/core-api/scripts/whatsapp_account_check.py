"""READ-ONLY check of the real Meta WhatsApp setup behind services/core-api/.env.

Answers, from Meta itself: is the token valid (type, expiry, permissions)? is WHATSAPP_APP_SECRET the app's real
secret? which number is WHATSAPP_PHONE_NUMBER_ID, is it registered on Cloud API, and is it also still on the
WhatsApp Business app (coexistence)? is the app subscribed to the WABA's webhooks, with which callback URL and
fields? which message templates are approved?

It only sends GET requests to graph.facebook.com — it never registers, migrates, deregisters, subscribes or sends
anything. It never prints the token or the app secret, and masks phone numbers to their last 3 digits.

Usage (from services/core-api):  .venv\\Scripts\\python scripts\\whatsapp_account_check.py
"""

import hashlib
import hmac
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weza.config import get_settings, is_configured  # noqa: E402

PHONE_FIELDS = ("display_phone_number,verified_name,code_verification_status,quality_rating,platform_type,status,"
                "name_status,account_mode,messaging_limit_tier,is_on_biz_app,throughput,is_official_business_account")


def mask(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return f"…{digits[-3:]} ({len(digits)} digits)" if digits else None


class Graph:
    def __init__(self, s):
        self.s, self.base = s, f"https://graph.facebook.com/{s.graph_api_version}"

    def get(self, path: str, params: dict | None = None, *, token: str | None = None, proof: bool = False) -> dict:
        tok = token or self.s.whatsapp_token or ""
        p = {**(params or {}), "access_token": tok}
        if proof:
            p["appsecret_proof"] = hmac.new((self.s.whatsapp_app_secret or "").encode(), tok.encode(),
                                            hashlib.sha256).hexdigest()
        try:
            r = httpx.get(f"{self.base}/{path}", params=p, timeout=15)
        except httpx.HTTPError as exc:
            return {"_error": {"network": type(exc).__name__}}
        try:
            d = r.json()
        except ValueError:
            return {"_error": {"http": r.status_code, "message": "non-JSON response"}}
        if isinstance(d, dict) and isinstance(d.get("error"), dict):
            e = d["error"]
            return {"_error": {"http": r.status_code, **{k: e.get(k) for k in ("code", "error_subcode", "type",
                                                                                 "message")}}}
        return d if isinstance(d, dict) else {"_error": {"message": "unexpected response"}}


def check(s, out=print) -> dict:
    """Run every check; returns a findings dict (also printed). Safe to call with mocked httpx."""
    g, f = Graph(s), {}
    missing = [n for n, v in (("WHATSAPP_TOKEN", s.whatsapp_token), ("WHATSAPP_PHONE_NUMBER_ID",
                                                                    s.whatsapp_phone_number_id)) if not is_configured(v)]
    if missing:
        out(f"Not configured: {', '.join(missing)}. Fill services/core-api/.env (scripts/configure_env.py) first.")
        return {"missing": missing}
    out(f"Graph API version: {s.graph_api_version}")

    dt = g.get("debug_token", {"input_token": s.whatsapp_token})
    if "data" in dt:
        x = dt["data"]
        f["token"] = {"valid": x.get("is_valid"), "type": x.get("type"), "app_id": x.get("app_id"),
                      "expires_at": x.get("expires_at") or "never", "scopes": x.get("scopes")}
    else:
        f["token"] = dt
    out("\n## Access token\n" + json.dumps(f["token"], indent=1, default=str))
    if "_error" in f["token"]:
        out("\n>>> The token is not usable (an expired temporary token gives code 190). Create a System User token in "
            "Meta Business Settings (see docs/WHATSAPP_GO_LIVE.md) and run this again.")
        return f

    me = g.get("me", {"fields": "id"}, proof=True)
    f["app_secret_matches_token_app"] = "_error" not in me
    out(f"\n## App secret\nWHATSAPP_APP_SECRET belongs to the token's app: {f['app_secret_matches_token_app']}"
        + ("" if f["app_secret_matches_token_app"] else f"  ({me['_error'].get('message')})"))
    if not s.whatsapp_app_secret_format_ok:
        out("WARNING: WHATSAPP_APP_SECRET is not 32 hex characters, so every inbound webhook signature check will fail.")

    pn = g.get(s.whatsapp_phone_number_id, {"fields": PHONE_FIELDS})
    if "_error" in pn:  # some fields need newer versions or extra permissions: fall back to the basics
        pn = g.get(s.whatsapp_phone_number_id, {"fields": "display_phone_number,verified_name,"
                                                          "code_verification_status,quality_rating"})
    if "display_phone_number" in pn:
        want = re.sub(r"\D", "", s.whatsapp_business_number or "")
        pn["matches_WHATSAPP_BUSINESS_NUMBER"] = bool(want) and re.sub(r"\D", "", pn["display_phone_number"]) == want
        pn["display_phone_number"] = mask(pn["display_phone_number"])
    f["phone_number"] = pn
    out("\n## Phone number (WHATSAPP_PHONE_NUMBER_ID)\n" + json.dumps(pn, indent=1, default=str))
    if pn.get("is_on_biz_app") and pn.get("platform_type") == "CLOUD_API":
        out("=> Coexistence is active: the number works in the WhatsApp Business app AND on Cloud API.")
    elif pn.get("platform_type") == "CLOUD_API":
        out("=> Registered on Cloud API (not shared with the WhatsApp Business app).")
    elif "platform_type" in pn:
        out(f"=> platform_type={pn['platform_type']}: NOT usable on Cloud API yet (see docs/WHATSAPP_GO_LIVE.md).")
    if pn.get("account_mode") == "SANDBOX" or "test" in str(pn.get("verified_name", "")).lower():
        out("=> This looks like a Meta TEST number, not the organisation's own number.")

    waba = s.whatsapp_business_account_id
    if is_configured(waba):
        f["waba"] = g.get(waba, {"fields": "id,name,currency,timezone_id,account_review_status,"
                                           "business_verification_status,ownership_type"})
        nums = g.get(f"{waba}/phone_numbers", {"fields": "id,display_phone_number,verified_name,platform_type,"
                                                         "code_verification_status,is_on_biz_app"})
        for n in nums.get("data", []):
            n["is_WHATSAPP_PHONE_NUMBER_ID"] = n.get("id") == s.whatsapp_phone_number_id
            n["display_phone_number"] = mask(n.get("display_phone_number"))
        f["waba_phone_numbers"] = nums
        f["subscribed_apps"] = g.get(f"{waba}/subscribed_apps")
        tpl = g.get(f"{waba}/message_templates", {"fields": "name,status,language,category", "limit": 100})
        f["templates"] = tpl.get("data", tpl)
        for k, title in (("waba", "WhatsApp Business Account"), ("waba_phone_numbers", "Numbers in this WABA"),
                         ("subscribed_apps", "Apps subscribed to this WABA's webhooks"),
                         ("templates", "Message templates")):
            out(f"\n## {title}\n" + json.dumps(f[k], indent=1, default=str)[:4000])
    else:
        out("\n(WHATSAPP_BUSINESS_ACCOUNT_ID not set: skipping WABA, subscription and template checks.)")

    app_id = (f.get("token") or {}).get("app_id")
    if app_id and f["app_secret_matches_token_app"]:
        subs = g.get(f"{app_id}/subscriptions", token=f"{app_id}|{s.whatsapp_app_secret}")
        f["webhook"] = [{"object": x.get("object"), "callback_url": x.get("callback_url"), "active": x.get("active"),
                         "fields": [y.get("name") for y in x.get("fields", [])]}
                        for x in subs.get("data", [])] if "data" in subs else subs
        out("\n## App webhook configuration\n" + json.dumps(f["webhook"], indent=1, default=str))
    return f


if __name__ == "__main__":
    check(get_settings())
