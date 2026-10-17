#!/bin/sh
# Migrate, optionally seed demo data (never in production), then serve.
set -e
python -m alembic upgrade head
if [ "${SEED_DEMO:-false}" = "true" ]; then
  python -m weza.seed || echo "seed skipped"
fi
# Real environments: ensure marketplace config and (if BOOTSTRAP_ADMIN_* are set) the first WEZA administrator.
python -m weza.bootstrap --if-configured || echo "bootstrap skipped"
exec uvicorn weza.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
