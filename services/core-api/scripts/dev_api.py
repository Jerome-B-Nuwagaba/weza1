"""Local development: start/attach the embedded PostgreSQL (pgserver), migrate, seed once, then run the API.

Usage: python scripts/dev_api.py   (serves on http://localhost:8000)
"""

import os
import subprocess
import sys
from pathlib import Path

import pgserver

ROOT = Path(__file__).resolve().parents[1]
srv = pgserver.get_server(str(ROOT / ".pgdata"), cleanup_mode=None)
if "weza" not in srv.psql("SELECT datname FROM pg_database;"):
    srv.psql("CREATE DATABASE weza;")
url = srv.get_uri().rsplit("/", 1)[0] + "/weza"
env = {**os.environ, "DATABASE_URL": url, "RUN_WORKER_INPROCESS": "true", "CORS_ORIGINS": "*", "SEED_DEMO": "true"}
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True)
subprocess.run([sys.executable, "-m", "weza.seed"], cwd=ROOT, env=env, check=False)
sys.exit(subprocess.call([sys.executable, "-m", "uvicorn", "weza.main:app", "--port", "8000"], cwd=ROOT, env=env))
