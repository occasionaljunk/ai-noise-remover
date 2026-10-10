#!/usr/bin/env bash
# Double-click to stop the Noise Remover server.
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
PIDS=$(lsof -ti tcp:"$PORT" -sTCP:LISTEN)
if [ -n "$PIDS" ]; then
  kill $PIDS && echo "Noise Remover stopped."
else
  echo "Noise Remover isn't running."
fi
rm -f .server.pid
