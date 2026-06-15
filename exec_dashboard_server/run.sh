#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -d ".venv" ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

if [[ -x ".venv/bin/python" ]]; then
  PY_CMD=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY_CMD="python3"
else
  echo "Error: no Python interpreter found (.venv/bin/python or python3)."
  exit 1
fi

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"
"$PY_CMD" exec_dashboard_server/server.py
