#!/usr/bin/env bash
# One entrypoint for daedalus. Uses the project venv if present.
set -euo pipefail
cd "$(dirname "$0")"

PY="./.venv/bin/python"
[ -x "$PY" ] || PY="python3"

case "${1:-help}" in
  setup)
    /opt/homebrew/bin/python3.12 -m venv .venv 2>/dev/null || python3 -m venv .venv
    ./.venv/bin/python -m pip install -q --upgrade pip
    ./.venv/bin/python -m pip install -q -e ".[dev]"
    [ -f .env ] || cp .env.example .env
    echo "setup done. edit .env, then: ./run.sh job https://developer.nvidia.com"
    ;;
  test)    "$PY" -m pytest "${@:2}" ;;
  cov)     "$PY" -m coverage run -m pytest && "$PY" -m coverage report -m \
             --include="daedalus/ledger.py,daedalus/spend_control.py,daedalus/pricing.py,daedalus/jobs/audit.py" ;;
  demo)    "$PY" -m daedalus.cli demo "${@:2}" ;;
  job)     "$PY" -m daedalus.cli job "${@:2}" ;;
  approve) "$PY" -m daedalus.cli approve "${@:2}" ;;
  audit)   "$PY" -m daedalus.cli audit "${@:2}" ;;
  pnl)     "$PY" -m daedalus.cli pnl ;;
  *) echo "usage: ./run.sh {setup|test|cov|demo|job|approve|audit|pnl}" ;;
esac
