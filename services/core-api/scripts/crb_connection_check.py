"""Check the GnuGrid CRB connection WITHOUT making an enquiry: requests an access token only.

No customer data is sent, no enquiry is made, nothing is charged. Prints whether the base URL is reachable and the
client credentials are accepted — never the token or the secret.

Usage (from services/core-api):  .venv\\Scripts\\python scripts\\crb_connection_check.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from weza.config import get_settings  # noqa: E402
from weza.domains.verification import gnugrid  # noqa: E402


def main() -> int:
    s = get_settings()
    if s.crb_missing:
        print("Not configured:", ", ".join(s.crb_missing), "— fill them with scripts/configure_env.py")
        return 2
    token, failure = gnugrid._token()
    if failure:
        print(f"FAILED: {failure.category} (HTTP {failure.http_status}) {failure.message}")
        return 1
    print("OK: GnuGrid accepted the client credentials (token received; not shown). No enquiry was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
