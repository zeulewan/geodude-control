#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
LOGFILE="${TMPDIR:-/tmp}/geodude_mizi_dev_local.log"
SESSION_NAME="geodude-mizi-dev"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install flask
fi

if lsof -nP -iTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "mizi-dev already running on 8081"
  exit 0
fi

cd "$ROOT/groundstation"
screen -dmS "$SESSION_NAME" zsh -lc "cd '$ROOT/groundstation' && '$VENV/bin/python' run_local_dev.py >>'$LOGFILE' 2>&1"
sleep 2
lsof -nP -iTCP:8081 -sTCP:LISTEN
echo "log: $LOGFILE"
