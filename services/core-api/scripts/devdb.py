"""Start a throwaway local PostgreSQL (via pgserver) for development and tests on machines without Docker.

Usage:  python scripts/devdb.py            -> prints DATABASE_URL and keeps running
"""

import sys
import time
from pathlib import Path

import pgserver


def start(data_dir: str | None = None) -> str:
    path = Path(data_dir or Path(__file__).resolve().parents[1] / ".pgdata")
    srv = pgserver.get_server(str(path), cleanup_mode=None)
    uri = srv.get_uri()
    return uri


if __name__ == "__main__":
    uri = start(sys.argv[1] if len(sys.argv) > 1 else None)
    print(uri, flush=True)
    while True:
        time.sleep(3600)
