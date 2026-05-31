#!/usr/bin/env bash
set -euo pipefail

# 定位项目根目录，确保无论从哪里执行脚本，Python 都能按包名导入 backend。
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 本地开发默认使用用户指定的 conda 环境；也允许临时覆盖环境名。
CONDA_ENV_NAME="${CONDA_ENV_NAME:-lang_graph}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
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

# 同时启动前后端；任一进程退出时，trap 会负责关闭另一个进程，避免留下孤儿服务。
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

trap cleanup EXIT INT TERM

echo "Starting comaic backend on http://${BACKEND_HOST}:${BACKEND_PORT}"
python -m uvicorn backend.main:app \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  --reload &
BACKEND_PID="$!"

echo "Starting comaic frontend on http://${FRONTEND_HOST}:${FRONTEND_PORT}"
npm --prefix frontend run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" &
FRONTEND_PID="$!"

echo
echo "comaic dev services are running:"
echo "  Backend : http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "  Frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both services."

wait -n "${BACKEND_PID}" "${FRONTEND_PID}"
