#!/usr/bin/env bash
# 把当前工作区同步到 VPS，并重建 / 重启应用容器。
#
# 用法：
#     ./scripts/deploy_vps.sh                 # 默认：本地测试 -> rsync -> 构建 -> 重启 -> 健康检查
#     SKIP_TESTS=1 ./scripts/deploy_vps.sh    # 跳过本地 pytest
#     ./scripts/deploy_vps.sh --static-only   # 只同步 static/，不重建镜像
#     REMOTE=root@1.2.3.4 ./scripts/deploy_vps.sh
#
# 注意：
# - 不会同步 .env、.data、模型权重；它们保留在服务器上。
# - 不会使用 rsync --delete，避免误删服务器上的运行期文件。
# - 修改切块规则后，仍需手动重建 Milvus collection，见 README。

set -euo pipefail

REMOTE="${REMOTE:-vps}"
REMOTE_DIR="${REMOTE_DIR:-/opt/claims-ai-agent}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
    -h|--help)
        usage
        exit 0
        ;;
    --static-only)
        echo "==> rsync static/"
        rsync -az static/ "$REMOTE:$REMOTE_DIR/static/"
        echo "==> done：static 已同步，静态资源通过 bind mount 立即生效"
        exit 0
        ;;
    "")
        ;;
    *)
        echo "未知参数：$1" >&2
        usage >&2
        exit 2
        ;;
esac

if [[ "${SKIP_TESTS:-0}" != "1" && -x .venv-py315/bin/python ]]; then
    echo "==> 本地测试"
    .venv-py315/bin/python -m pytest -q
fi

echo "==> rsync 代码到 $REMOTE:$REMOTE_DIR"
rsync -az \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '.env.*' \
    --exclude '.data' \
    --exclude '.venv*' \
    --exclude '__pycache__' \
    --exclude '*.py[cod]' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude '.mypy_cache' \
    --exclude '.DS_Store' \
    --exclude '*.log' \
    --exclude '.coverage' \
    --exclude 'htmlcov' \
    --exclude 'models/bge-m3' \
    --exclude 'models/bge-reranker-base' \
    --exclude 'My_Study' \
    --exclude 'isolated_deep' \
    ./ "$REMOTE:$REMOTE_DIR/"

echo "==> 构建镜像"
ssh "$REMOTE" "cd '$REMOTE_DIR' && docker compose -f '$COMPOSE_FILE' build app embed"

echo "==> 启动 / 重建容器"
ssh "$REMOTE" "cd '$REMOTE_DIR' && docker compose -f '$COMPOSE_FILE' up -d --no-build embed && docker compose -f '$COMPOSE_FILE' up -d --no-build --force-recreate app"

echo "==> 健康检查"
ssh "$REMOTE" "for i in \$(seq 1 30); do if curl -fsS http://127.0.0.1:8001/health >/dev/null 2>&1; then curl -fsS http://127.0.0.1:8001/ready && echo && exit 0; fi; sleep 2; done; echo '健康检查超时' >&2; exit 1"

echo "==> 完成：https://aiwanxiang.top/ai/"
