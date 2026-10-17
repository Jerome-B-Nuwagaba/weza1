"""First-run setup for a REAL (non-demo) environment: marketplace configuration + the first WEZA administrator.

Without this a deployment started with SEED_DEMO=false has no WEZA staff, so nobody could verify institutions that
apply to join. Safe to run on every start (idempotent, never touches existing users, never creates demo data).

Interactive (hidden password):   python -m weza.bootstrap
Unattended (platform env vars):  BOOTSTRAP_ADMIN_EMAIL, BOOTSTRAP_ADMIN_NAME, BOOTSTRAP_ADMIN_PASSWORD
                                 then  python -m weza.bootstrap --if-configured

>>> USER INPUT REQUIRED: choose the first administrator's real email and a strong password (12+ characters).
Never commit them; set the BOOTSTRAP_* variables only in the hosting platform's secret settings or type them here.
"""

import getpass
import os
import sys

from sqlalchemy import select

import weza.consumers  # noqa: F401
from weza.domains.identity import service as identity
from weza.domains.identity.models import User
from weza.platform.db import session_scope
from weza.seed import seed_config

WEZA_ROLES = ["WEZA_SUPER", "WEZA_OPS", "WEZA_COMMERCIAL"]


def ensure_config() -> None:
    with session_scope() as db:
        seed_config(db)


def weza_admin_exists() -> bool:
    with session_scope() as db:
        return db.execute(select(User.id).where(User.kind == "WEZA").limit(1)).first() is not None


def create_admin(email: str, name: str, password: str) -> bool:
    """Creates the first WEZA administrator unless a WEZA user with that email exists. Returns True if created."""
    with session_scope() as db:
        if db.execute(select(User.id).where(User.email == email.strip().lower())).first():
            return False
        identity.create_user(db, email=email, full_name=name, password=password, kind="WEZA", weza_roles=WEZA_ROLES)
        return True


def main(argv: list[str]) -> int:
    ensure_config()
    email = os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip()
    password = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    name = os.environ.get("BOOTSTRAP_ADMIN_NAME", "").strip() or "WEZA Administrator"
    if email and password:
        made = create_admin(email, name, password)
        print("WEZA administrator created." if made else "WEZA administrator already exists; nothing changed.")
        return 0
    if "--if-configured" in argv:
        print("Marketplace configuration ensured. No BOOTSTRAP_ADMIN_* set; skipping administrator.")
        return 0
    if weza_admin_exists():
        print("A WEZA administrator already exists; nothing to do.")
        return 0
    email = input("First WEZA administrator email: ").strip()
    name = input("Full name: ").strip() or "WEZA Administrator"
    password = getpass.getpass("Password (12+ characters, hidden): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return 1
    print("Administrator created." if create_admin(email, name, password) else "That email already exists.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
