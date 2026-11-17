#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.txt
docker compose up -d --wait
.venv/bin/python seed_pgvector.py
echo 'MeowMatch: http://localhost:8000'
exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8000
