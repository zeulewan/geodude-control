#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
LOGFILE="${TMPDIR:-/tmp}/geodude_mizi_dev_local.log"
SESSION_NAME="geodude-mizi-dev"
UPSTREAM_GS="${UPSTREAM_GROUNDSTATION_URL:-http://192.168.50.2:8080}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [ -z "$PYTHON_BIN" ]; then
  if [ -x /usr/bin/python3 ]; then
    PYTHON_BIN="/usr/bin/python3"
  elif command -v python3.11 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.11)"
  elif command -v python3.10 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.10)"
  elif command -v python3.9 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.9)"
  elif command -v python3.13 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3.13)"
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

if ! "$VENV/bin/python" - <<'PY' >/dev/null 2>&1
import flask
import numpy
import PIL
import torch
import ultralytics
import cv2
PY
then
  "$VENV/bin/pip" install -q flask pillow 'numpy<2' torch ultralytics ultralytics-thop opencv-python-headless==4.10.0.84
fi

if lsof -nP -iTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "mizi-dev already running on 8081"
  exit 0
fi

cd "$ROOT/groundstation"
screen -dmS "$SESSION_NAME" zsh -lc "cd '$ROOT/groundstation' && UPSTREAM_GROUNDSTATION_URL='$UPSTREAM_GS' '$VENV/bin/python' run_local_dev.py >>'$LOGFILE' 2>&1"
for _ in {1..20}; do
  if lsof -nP -iTCP:8081 -sTCP:LISTEN >/dev/null 2>&1; then
    lsof -nP -iTCP:8081 -sTCP:LISTEN
    echo "log: $LOGFILE"
    exit 0
  fi
  sleep 1
done
echo "mizi-dev failed to start on 8081"
tail -n 80 "$LOGFILE" || true
exit 1
