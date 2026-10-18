r"""Check the GnuGrid CRB connection WITHOUT making an enquiry: requests an access token only.

No customer data is sent, no enquiry is made, nothing is charged. Prints whether the base URL is reachable and the
client credentials are accepted — never the token or the secret.

Usage (from services/core-api, with GNUGRID_* set in the environment or .env):
    .venv\Scripts\python scripts\crb_connection_check.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weza.config import get_settings  # noqa: E402
from weza.integrations import gnugrid  # noqa: E402


def main() -> int:
    s = get_settings()
    if s.crb_missing:
        print("Not configured:", ", ".join(s.crb_missing))
        return 2
    try:
        gnugrid.GNUGridClient().token()
    except gnugrid.CRBError as exc:
        print(f"FAILED: {exc.category} (HTTP {exc.http_status}) {exc.message}")
        return 1
    print(f"OK: GnuGrid at {s.gnugrid_base_url} accepted the client credentials (token received; not shown). "
          "No enquiry was made, nothing was charged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
