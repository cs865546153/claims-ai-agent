#!/usr/bin/env bash
# 交互式写入 DeepSeek API Key：不回显、不进 shell 历史，写完后做一次连通性校验。
# 用法：bash scripts/set_deepseek_key.sh
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "已从 .env.example 创建 .env"
fi

printf '请输入 DeepSeek API Key（输入不显示，回车确认）: '
IFS= read -r -s key
printf '\n'
if [[ -z "${key}" ]]; then
  echo "未输入，已取消（.env 未修改）。" >&2
  exit 1
fi

tmp="$(mktemp)"
awk -v k="$key" '
  /^DEEPSEEK_API_KEY=/ { print "DEEPSEEK_API_KEY=" k; found=1; next }
  { print }
  END { if (!found) print "DEEPSEEK_API_KEY=" k }
' .env > "$tmp"
mv "$tmp" .env
sed -i '' 's/^MODEL_PROVIDER=.*/MODEL_PROVIDER=deepseek/' .env
chmod 600 .env
unset key
echo "已写入 .env（MODEL_PROVIDER=deepseek），开始校验..."

exec .venv-py315/bin/python - <<'PY'
import sys

import httpx

from settings import Settings

settings = Settings()
if settings.model_provider != 'deepseek':
    sys.exit('MODEL_PROVIDER 不是 deepseek，请检查 .env')
key = settings.deepseek_api_key.get_secret_value()
if not key:
    sys.exit('DEEPSEEK_API_KEY 为空')

try:
    response = httpx.get(
        f'{settings.deepseek_base_url}/models',
        headers={'Authorization': f'Bearer {key}'},
        timeout=20,
    )
except Exception as exc:
    sys.exit(f'连接 {settings.deepseek_base_url} 失败：{type(exc).__name__}: {exc}')
if response.status_code != 200:
    sys.exit(f'鉴权失败 HTTP {response.status_code}：{response.text[:200]}')

ids = [item.get('id') for item in response.json().get('data', [])]
print('可用模型:', ', '.join(str(i) for i in ids) or '（空列表）')
missing = [name for name in (settings.deepseek_flash_model, settings.deepseek_pro_model) if name not in ids]
for name in (settings.deepseek_flash_model, settings.deepseek_pro_model):
    print(('  OK      ' if name not in missing else '  未在列表 ') + name)
if missing:
    print('警告：上面标“未在列表”的模型名与账号可用列表不一致，请改名后重启，否则调用会返回 400。')
else:
    print('配置可用。启动：bash scripts/start_mac.sh')
PY
