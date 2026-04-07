#!/bin/zsh
set -euo pipefail

SESSION_NAME="geodude-mizi-dev"
PORT_PID="$(lsof -tiTCP:8081 -sTCP:LISTEN || true)"

if [ -n "$PORT_PID" ]; then
  kill "$PORT_PID"
  echo "stopped mizi-dev pid $PORT_PID"
else
  echo "mizi-dev is not running on 8081"
fi

if screen -list | grep -q "[.]$SESSION_NAME"; then
  screen -S "$SESSION_NAME" -X quit
fi
