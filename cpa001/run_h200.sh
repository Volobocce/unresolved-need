#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${1:-}" == "--smoke" ]]; then
  shift
  exec python3 src/cpa_battery.py --smoke "$@"
else
  exec python3 src/cpa_battery.py "$@"
fi
