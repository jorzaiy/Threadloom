#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
APP_ROOT="$(cd "$DIR/.." && pwd)"

if [[ -f "$APP_ROOT/.env.local" ]]; then
  # Load user-local secrets for provider config env:VAR references.
  set -a
  # shellcheck disable=SC1091
  . "$APP_ROOT/.env.local"
  set +a
fi

PID_FILE="$DIR/threadloom.pid"
LOG_FILE="$DIR/threadloom.log"
HEALTH_URL="http://127.0.0.1:8765/api/health"

MODE="foreground"
if [[ "${1:-}" == "--daemon" ]]; then
  MODE="daemon"
fi

if [[ "$MODE" == "daemon" ]]; then
  if [[ -f "$PID_FILE" ]]; then
    old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
      echo "threadloom backend already running (pid=$old_pid)"
      exit 0
    fi
    rm -f "$PID_FILE"
  fi

  nohup python3 server.py >>"$LOG_FILE" 2>&1 &
  new_pid=$!
  echo "$new_pid" >"$PID_FILE"

  sleep 1
  if kill -0 "$new_pid" 2>/dev/null && curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "threadloom backend started in daemon mode (pid=$new_pid)"
    echo "log: $LOG_FILE"
  else
    echo "----- threadloom.log (tail) -----" >&2
    tail -n 40 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    echo "threadloom backend failed to start in daemon mode" >&2
    exit 1
  fi
  exit 0
fi

echo "threadloom backend starting in foreground on http://127.0.0.1:8765"
exec python3 server.py
