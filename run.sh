#!/usr/bin/env bash
# Start the noise remover on http://localhost:8765 (use HOST=0.0.0.0 to expose on your network)
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8765}"
