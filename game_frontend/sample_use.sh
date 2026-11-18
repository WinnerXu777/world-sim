#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PYTHON="${ROOT_DIR}/.venv/Scripts/python.exe"
FRONTEND_DIR="${ROOT_DIR}/game_frontend"
BACKEND_PORT="${BACKEND_PORT:-8002}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

if [[ ! -f "${BACKEND_PYTHON}" ]]; then
  echo "Missing backend python at ${BACKEND_PYTHON}"
  echo "Create the venv first from the repo root:"
  echo "  python -m venv .venv"
  exit 1
fi

echo "Installing frontend packages if needed..."
cd "${FRONTEND_DIR}"
npm install

echo "Starting backend on ${BACKEND_URL}"
"${BACKEND_PYTHON}" -m uvicorn map_test:app --host 127.0.0.1 --port "${BACKEND_PORT}" --app-dir "${ROOT_DIR}/at_the_beginning" &
BACKEND_PID=$!

cleanup() {
  kill "${BACKEND_PID}" "${FRONTEND_PID:-0}" 2>/dev/null || true
}
trap cleanup EXIT

echo "Starting frontend on http://127.0.0.1:${FRONTEND_PORT}"
VITE_BACKEND_URL="${BACKEND_URL}" npm run dev -- --host=127.0.0.1 --port="${FRONTEND_PORT}" &
FRONTEND_PID=$!

wait "${FRONTEND_PID}"
