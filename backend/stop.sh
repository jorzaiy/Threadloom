#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PID_FILE="$DIR/threadloom.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "threadloom backend is not running"
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -z "$pid" ]]; then
  rm -f "$PID_FILE"
  echo "threadloom backend pid file was empty"
  exit 0
fi

if kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid"
  fi
  echo "threadloom backend stopped (pid=$pid)"
else
  echo "threadloom backend process not found (pid=$pid)"
fi

rm -f "$PID_FILE"
