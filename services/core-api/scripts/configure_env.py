"""Interactive setup for your WhatsApp / SMS settings. Run it yourself in your own terminal:

    cd services\\core-api
    .venv\\Scripts\\python scripts\\configure_env.py

It asks for each WHATSAPP_* and SMS_* setting listed in .env.example (hidden input for secrets), skips anything you
leave blank, and writes ONLY to the untracked services/core-api/.env. It refuses to run unless git ignores that file.
It never prints, logs or echoes a value; at the end it lists only which names are set and which are not.
"""

import getpass
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("WHATSAPP_", "SMS_")
SECRETS = {"WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_TOKEN", "SMS_API_KEY"}
PLACEHOLDER = "REPLACE_ME"
_KEY = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def is_set(value: str | None, name: str = "") -> bool:
    v = (value or "").strip().strip('"').strip("'")
    if name == "SMS_PROVIDER" and v.lower() in ("console", "simulator"):
        return False  # the no-real-SMS default
    return bool(v) and v.upper() != PLACEHOLDER


def git_ignores(path: Path) -> bool:
    try:
        r = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=path.parent, capture_output=True, check=False)
    except OSError:
        return False
    return r.returncode == 0


def managed_settings(example: Path) -> list[tuple[str, str]]:
    """[(NAME, help text)] for every WHATSAPP_*/SMS_* key in .env.example, with its preceding comment lines."""
    out, notes = [], []
    for line in example.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            notes.append(line.lstrip("# ").strip())
            continue
        m = _KEY.match(line)
        if m and m.group(1).startswith(PREFIXES):
            help_ = " ".join(n for n in notes if n and not n.startswith("---") and "USER INPUT" not in n)
            out.append((m.group(1), help_[-180:]))
        if not line.startswith("#"):
            notes = []
    return out


def read_env(path: Path) -> dict[str, str]:
    vals = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _KEY.match(line)
        if m:
            vals[m.group(1)] = m.group(2).strip()
    return vals


def encode(value: str) -> str:
    return f'"{value}"' if re.search(r"[\s#]", value) else value


def write_value(path: Path, name: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    new = f"{name}={encode(value)}"
    for i, line in enumerate(lines):
        if line.startswith(name + "="):
            lines[i] = new
            break
    else:
        lines.append(new)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run(root: Path = ROOT, ask: Callable[[str], str] = input, ask_secret: Callable[[str], str] = getpass.getpass,
        ignored: Callable[[Path], bool] = git_ignores, out: Callable[[str], None] = print) -> int:
    env, example = root / ".env", root / ".env.example"
    if not ignored(env):
        out("Refusing to run: git does not ignore services/core-api/.env, so real values could be committed.")
        out("Fix .gitignore first (it should contain '.env').")
        return 2
    settings = managed_settings(example)
    if not env.exists():
        # Only the managed keys: the rest of .env.example holds placeholder secrets that would override the working
        # local development defaults (e.g. an invalid VAULT_MASTER_KEY).
        header = "# Local settings (untracked). Created by scripts/configure_env.py — never commit this file.\n"
        env.write_text(header + "".join(f"{n}={PLACEHOLDER}\n" for n, _ in settings), encoding="utf-8", newline="\n")
        out("Created services/core-api/.env (untracked) with placeholders.")
    out("Enter a value for each setting, or press Enter to leave it unchanged. Values are never shown or logged.\n")
    current = read_env(env)
    changed = 0
    for name, help_ in settings:
        status = "already set" if is_set(current.get(name), name) else "not set"
        out(f"{name}  [{status}]" + (f"\n  {help_}" if help_ else ""))
        try:
            value = (ask_secret if name in SECRETS else ask)(f"  {name}: ").strip()
        except (EOFError, KeyboardInterrupt):
            out("\nStopped. Nothing further was written.")
            break
        if not value or "\n" in value or "\r" in value:
            continue
        write_value(env, name, value)
        changed += 1
    final = read_env(env)
    out(f"\nUpdated {changed} setting(s) in services/core-api/.env.")
    out("SET:   " + (", ".join(n for n, _ in settings if is_set(final.get(n), n)) or "(none)"))
    out("UNSET: " + (", ".join(n for n, _ in settings if not is_set(final.get(n), n)) or "(none)"))
    out("\nRestart the API to load changes. The startup log lists configured/missing names (never values).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
