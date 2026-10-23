#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# 使用独立检查点库，验证过程中不读写业务案件。
# 虚拟环境可用 VENV_DIR 覆盖；默认优先 .venv-py315，其次 .venv-py314。
if [[ -z "${VENV_DIR:-}" ]]; then
  for candidate in .venv-py315 .venv-py314; do
    if [[ -x "$candidate/bin/uvicorn" ]]; then VENV_DIR="$candidate"; break; fi
  done
fi
if [[ -z "${VENV_DIR:-}" || ! -x "$VENV_DIR/bin/uvicorn" ]]; then
  echo "未找到可用的虚拟环境（试过 .venv-py315 / .venv-py314）；请先按 README 安装，或用 VENV_DIR 指定。" >&2
  exit 1
fi
check_dir="$(mktemp -d)"
CLAIMS_CHECKPOINT_DB="$check_dir/checkpoints.sqlite" "$VENV_DIR/bin/uvicorn" app:app --host 127.0.0.1 --port 8001 > "$check_dir/uvicorn.log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
ready=false
for attempt in {1..30}; do
  if ! kill -0 "$server_pid" 2>/dev/null; then cat "$check_dir/uvicorn.log"; exit 1; fi
  if curl -fsS http://127.0.0.1:8001/health >/dev/null; then ready=true; break; fi
  sleep 1
done
if [[ "$ready" != true ]]; then cat "$check_dir/uvicorn.log"; exit 1; fi
"$VENV_DIR/bin/python" health_check.py --url http://127.0.0.1:8001
SMOKE_BASE_URL=http://127.0.0.1:8001 "$VENV_DIR/bin/python" -m pytest -q tests/test_smoke.py
