#!/usr/bin/env bash
# Set up (once) and launch Relabel.
#
#   ./run.sh [FOLDER] [options]     open a project folder (same options as python -m relabel_gui_app)
#   ./run.sh --demo                 open the bundled street-crossing example
#
# First run: creates .venv and installs numpy + scipy (tracker) and anthropic (Ask AI).
# Later runs: finds everything already installed and starts straight away.
set -euo pipefail

cd "$(dirname "$0")"
VENV=.venv

find_python() {
  for py in python3 python py; do
    if command -v "$py" >/dev/null 2>&1 &&
       "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
      echo "$py"; return 0
    fi
  done
  return 1
}

if [ -x "$VENV/bin/python" ]; then
  PY="$VENV/bin/python"
elif [ -x "$VENV/Scripts/python.exe" ]; then            # Windows (Git Bash)
  PY="$VENV/Scripts/python.exe"
else
  SYS_PY=$(find_python) || { echo "Python 3.8 or newer is required: https://www.python.org/downloads/" >&2; exit 1; }
  echo "Creating virtual environment in $VENV ..."
  "$SYS_PY" -m venv "$VENV"
  if [ -x "$VENV/bin/python" ]; then PY="$VENV/bin/python"; else PY="$VENV/Scripts/python.exe"; fi
fi

if "$PY" -c 'import numpy, scipy, anthropic' >/dev/null 2>&1; then
  echo "Dependencies already installed, skipping download."
else
  echo "Installing dependencies (numpy, scipy, anthropic) ..."
  "$PY" -m pip install --disable-pip-version-check -q -r requirements.txt
fi

if [ "${1:-}" = "--demo" ]; then
  shift
  set -- examples "$@"
fi

exec "$PY" -m relabel_gui_app "$@"
