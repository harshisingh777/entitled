#!/usr/bin/env bash
# Sets up on first run, then starts both servers. Open http://localhost:3000
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"
python_bin="$root/backend/.venv/bin/python"

if [ ! -x "$python_bin" ]; then
  python3 -m venv "$root/backend/.venv"
  "$python_bin" -m pip install -q -r "$root/backend/requirements.txt"
  "$python_bin" -m playwright install chromium
fi
[ -d "$root/frontend/node_modules" ] || npm --prefix "$root/frontend" install
[ -f "$root/frontend/.next/BUILD_ID" ] || npm --prefix "$root/frontend" run build

(cd "$root/backend" && "$python_bin" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT
echo "Entitled is starting at http://localhost:3000 (Ctrl+C to stop)"
npm --prefix "$root/frontend" run start
