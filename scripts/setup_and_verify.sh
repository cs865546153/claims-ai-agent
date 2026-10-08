#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# 可用PYTHON_BIN覆盖；本机默认采用 Python 3.14。
"${PYTHON_BIN:-python3.14}" -m venv .venv-py314
source .venv-py314/bin/activate
python -m pip install -r requirements.txt
python -m pip check
if [[ ! -f .env ]]; then cp .env.example .env; chmod 600 .env; fi
python -m pytest -q
bash scripts/verify.sh
