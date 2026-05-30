#!/usr/bin/env bash
set -euo pipefail

# 定位项目根目录，确保无论从哪里执行脚本，Python 都能按包名导入 backend。
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 本地开发默认使用用户指定的 conda 环境；也允许临时覆盖环境名。
CONDA_ENV_NAME="${CONDA_ENV_NAME:-lang_graph}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

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

echo "Starting comaic backend on http://${HOST}:${PORT}"
python -m uvicorn backend.main:app --host "${HOST}" --port "${PORT}" --reload
