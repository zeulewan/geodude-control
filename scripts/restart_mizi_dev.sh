#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/stop_mizi_dev.sh" || true
sleep 1
"$ROOT/scripts/start_mizi_dev.sh"
