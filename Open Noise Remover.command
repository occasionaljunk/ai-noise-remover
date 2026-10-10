#!/usr/bin/env bash
# Double-click to start the Noise Remover (if needed) and open it in your browser.
cd "$(dirname "$0")"
PORT="${PORT:-8765}"
URL="http://localhost:$PORT"

if ! curl -s -o /dev/null "$URL"; then
  echo "Starting Noise Remover…"
  nohup .venv/bin/uvicorn app:app --host 127.0.0.1 --port "$PORT" > server.log 2>&1 &
  echo $! > .server.pid
  for _ in $(seq 1 60); do
    curl -s -o /dev/null "$URL" && break
    sleep 1
  done
fi

if curl -s -o /dev/null "$URL"; then
  open "$URL"
  echo "Noise Remover is running at $URL — you can close this window."
else
  echo "Server failed to start. See server.log:"
  tail -20 server.log
  read -n 1 -s -r -p "Press any key to close…"
fi
