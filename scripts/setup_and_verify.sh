#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# 可用 PYTHON_BIN 覆盖；默认优先 Python 3.15，其次 3.14（项目要求 3.12+）。
PYTHON_BIN="${PYTHON_BIN:-$(command -v python3.15 || command -v python3.14 || echo python3)}"
VENV_DIR="${VENV_DIR:-.venv-py315}"
"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
python -m pip install -r requirements.txt
python -m pip check
if [[ ! -f .env ]]; then cp .env.example .env; chmod 600 .env; fi
python -m pytest -q
bash scripts/verify.sh
