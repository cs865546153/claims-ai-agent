#!/usr/bin/env bash
# macOS / Linux 一键启动：不依赖当前目录，也不依赖是否已激活虚拟环境。
# 用法：
#   bash scripts/start_mac.sh              # 默认 8001，开发热重载开启
#   bash scripts/start_mac.sh 8002         # 指定端口
#   bash scripts/start_mac.sh --no-reload  # 关闭热重载（更接近生产）
# 日志：
#   应用 .data/logs/app.log；uvicorn .data/logs/uvicorn.log
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

port="${PORT:-8001}"
reload=1
for arg in "$@"; do
  case "$arg" in
    --no-reload|--no_reload) reload=0 ;;
    --reload) reload=1 ;;
    ''|*[!0-9]*) echo "未知参数：$arg（可用：端口号、--reload、--no-reload）" >&2; exit 2 ;;
    *) port="$arg" ;;
  esac
done

# 优先显式 VENV_DIR，其次 .venv-py315 / .venv-py314 / .venv。
if [[ -z "${VENV_DIR:-}" ]]; then
  for candidate in .venv-py315 .venv-py314 .venv; do
    if [[ -x "$candidate/bin/uvicorn" ]]; then VENV_DIR="$candidate"; break; fi
  done
fi
if [[ -z "${VENV_DIR:-}" || ! -x "$VENV_DIR/bin/uvicorn" ]]; then
  echo "未找到可用的虚拟环境（检查过 .venv-py315 / .venv-py314 / .venv）。" >&2
  echo "请先按 README「macOS 快速启动」安装依赖，或用 VENV_DIR 指定。" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "提示：未找到 .env，将使用代码内置默认（MODEL_PROVIDER=local → 127.0.0.1:8000）。" >&2
  echo "      推荐先写入 DeepSeek Key：bash scripts/set_deepseek_key.sh" >&2
fi

# 应用日志由 .env 的 LOG_FILE 控制（默认 .data/logs/app.log）；
# uvicorn 自身的启动/访问日志单独 tee 到 uvicorn.log。
log_dir="$root/.data/logs"
mkdir -p "$log_dir"
uvicorn_log="$log_dir/uvicorn.log"
app_log="${LOG_FILE:-}"
if [[ -z "$app_log" && -f .env ]]; then
  app_log="$(grep -E '^[[:space:]]*LOG_FILE=' .env | tail -n 1 | cut -d= -f2- | tr -d '\r')"
fi
app_log="${app_log:-.data/logs/app.log}"
export LOG_FILE="$app_log"

args=(app:app --host 127.0.0.1 --port "$port")
if [[ "$reload" == 1 ]]; then
  # watchfiles 已随 requirements 安装；显式排除虚拟环境、数据目录和学习目录，
  # 否则热重载会把这些目录里的 .py 也纳入监听。
  # 注意：uvicorn 的 exclude_dir 判断是 `exclude_dir in path.parents`，
  # 必须传绝对路径，相对路径不会生效。
  venv_abs="$(cd "$VENV_DIR" && pwd)"
  args+=(
    --reload
    --reload-exclude "$venv_abs"
    --reload-exclude "$root/.git"
    --reload-exclude "$root/.data"
    --reload-exclude "$root/My_Study"
  )
fi

echo "项目目录: $root"
echo "虚拟环境: $VENV_DIR"
echo "监听地址: http://127.0.0.1:$port/"
echo "热重载  : $([[ "$reload" == 1 ]] && echo '开（改代码自动重启）' || echo '关')"
echo "应用日志: $app_log（由 .env 的 LOG_FILE 控制）"
echo "uvicorn日志: $uvicorn_log"
"$VENV_DIR/bin/uvicorn" "${args[@]}" 2>&1 | tee -a "$uvicorn_log"
