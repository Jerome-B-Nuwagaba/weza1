"""READ-ONLY diagnosis: which business portfolio owns each WhatsApp account involved, and can a given token send?

Asks for a token with hidden input (e.g. a temporary token from Meta → WhatsApp → API Setup); it is never printed or
saved. Sends only GET requests, plus one send attempt to recipient "0", which cannot be a WhatsApp user, so nothing
can be delivered to anyone.

Usage (from services/core-api):  .venv\\Scripts\\python scripts\\whatsapp_owner_check.py [OTHER_ACCOUNT_ID ...]

Typical finding (2026-10-16): Meta's newer Business Settings screen lists a "WhatsApp business presence" whose ID is
NOT the WhatsApp Business Account ID. Assigning a system user to the presence lets it read the phone number but not
send ("(#10) Viewer cannot access the provided Paid Message Account <WABA_ID>"): assign the system user to the
WhatsApp Business Account itself (classic Business Settings or WhatsApp Manager → People).
"""

import getpass
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weza.config import get_settings  # noqa: E402


def main() -> None:
    s = get_settings()
    # WHATSAPP_BUSINESS_ACCOUNT_ID plus any IDs given on the command line (e.g. the asset ID from a Business Settings URL)
    accounts = [a for a in [(s.whatsapp_business_account_id or "").strip(), *sys.argv[1:]] if a.isdigit()]
    tok = getpass.getpass("Paste a temporary token from API Setup (hidden, Enter to use WHATSAPP_TOKEN): ").strip()
    tok = tok or (s.whatsapp_token or "").strip()
    g, h = f"https://graph.facebook.com/{s.graph_api_version}", {"Authorization": f"Bearer {tok}"}
    for oid in accounts:
        j = httpx.get(f"{g}/{oid}", params={"fields": "id,name,ownership_type,owner_business_info"}, headers=h,
                      timeout=20).json()
        if "error" in j:
            print(f"{oid}: cannot read ({j['error'].get('message', '')[:100]})")
        else:
            o = j.get("owner_business_info") or {}
            print(f"{oid}: name={j.get('name')!r} owner portfolio={o.get('name')!r} (id {o.get('id')})")
    r = httpx.post(f"{g}/{s.whatsapp_phone_number_id.strip()}/messages", headers=h, timeout=20,
                   json={"messaging_product": "whatsapp", "to": "0", "type": "text", "text": {"body": "check"}})
    e = r.json().get("error", {})
    print("send test with this token:", "permission OK (Meta accepted or rejected only the fake recipient)"
          if e.get("code") != 10 else f"BLOCKED: {e.get('message')}", f"[HTTP {r.status_code}, code {e.get('code')}]")


if __name__ == "__main__":
    main()
