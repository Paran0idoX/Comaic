#!/usr/bin/env bash
set -euo pipefail

# 定位项目根目录，确保无论从哪里执行脚本，Python 都能按包名导入 backend。
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 本地开发默认使用 comaic，也允许调用方通过环境变量临时覆盖。
CONDA_ENV_NAME="${CONDA_ENV_NAME:-comaic}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_HEALTH_HOST="${BACKEND_HEALTH_HOST:-${BACKEND_HOST}}"
BACKEND_STARTUP_TIMEOUT="${BACKEND_STARTUP_TIMEOUT:-60}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

cd "${PROJECT_ROOT}"

# 如果当前还没激活目标环境，尝试通过 conda shell hook 激活。
if [[ "${CONDA_DEFAULT_ENV:-}" != "${CONDA_ENV_NAME}" ]]; then
  if ! command -v conda >/dev/null 2>&1; then
    echo "未找到 conda，请先手动执行：conda activate ${CONDA_ENV_NAME}" >&2
    exit 1
  fi

  # shellcheck disable=SC1091
  eval "$(conda shell.bash hook)"
  conda activate "${CONDA_ENV_NAME}"
fi

# 统一管理前后端进程；任一进程退出时，trap 会负责关闭另一个进程，避免留下孤儿服务。
BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo
  echo "Stopping comaic dev services..."
  if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
  fi
}

wait_for_backend() {
  local health_url="http://${BACKEND_HEALTH_HOST}:${BACKEND_PORT}/health"
  local deadline=$((SECONDS + BACKEND_STARTUP_TIMEOUT))

  echo "Waiting for comaic backend health check at ${health_url}"
  while (( SECONDS < deadline )); do
    if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
      echo "Backend exited before becoming ready." >&2
      wait "${BACKEND_PID}" || true
      return 1
    fi

    if python -c 'import sys; from urllib.request import urlopen; response = urlopen(sys.argv[1], timeout=1); status = response.status; response.close(); raise SystemExit(0 if status == 200 else 1)' "${health_url}" >/dev/null 2>&1; then
      echo "Backend is ready."
      return 0
    fi

    sleep 0.5
  done

  echo "Backend did not become ready within ${BACKEND_STARTUP_TIMEOUT} seconds." >&2
  return 1
}

if [[ ! "${BACKEND_STARTUP_TIMEOUT}" =~ ^[1-9][0-9]*$ ]]; then
  echo "BACKEND_STARTUP_TIMEOUT must be a positive integer." >&2
  exit 1
fi

trap cleanup EXIT INT TERM

echo "Starting comaic backend on http://${BACKEND_HOST}:${BACKEND_PORT}"
python -m uvicorn backend.main:app \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  --reload &
BACKEND_PID="$!"

wait_for_backend

echo "Starting comaic frontend on http://${FRONTEND_HOST}:${FRONTEND_PORT}"
npm --prefix frontend run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" &
FRONTEND_PID="$!"

echo
echo "comaic dev services are running:"
echo "  Backend : http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "  Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both services."

wait -n "${BACKEND_PID}" "${FRONTEND_PID}"
