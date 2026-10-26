#!/usr/bin/env bash
# 3D Text Counter launcher for macOS / Linux
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "   3D TEXT COUNTER  -  starting up"
echo "============================================================"

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
  echo "[ERROR] Python 3.9+ is required but was not found."
  exit 1
fi

if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "Installing required packages (one time only)..."
  "$PY" -m pip install -r requirements.txt
fi

exec "$PY" app.py
