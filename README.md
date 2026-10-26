# 智能业务助手（Claims AI Agent）：理赔 + 投资 + 通用知识库 RAG

面向理赔审核、投资知识问答和通用知识库问答的一体化智能助手。主应用使用 **FastAPI + LangGraph**，核心能力包括：

- **理赔状态机**：报案、补材料、保单查询、三专家并行分析、置信度/风险决策、人工复核与断点恢复；
- **投资知识库 RAG**：`data/investment_wiki/`，BGE-M3 向量 + BM25 + 元数据三路召回，加权 RRF 后由 BGE-Reranker 精排；
- **通用知识库 RAG**：`data/knowledge_base/`，支持 Markdown/TXT/PDF/DOCX/HTML，提供 `/api/rag/search` 与 `/api/rag/answer`；
- **接入层**：RequestID、API Key/审核员认证、限流、PII 脱敏、审计哈希链、SSE 流式输出；
- **意图路由**：`agent_core/intent/` 提供 JEV / LLM / Hybrid / Shadow 四种模式，已接入
  `/api/assistant/stream`；代码默认 `shadow`（LLM 主路由 + JEV 影子），当前 `.env` 已配
  `INTENT_ENGINE=hybrid`（JEV 主 + LLM 兜底）；
- **部署**：Docker Compose + nginx `/ai/` 子路径，线上演示入口为 <https://aiwanxiang.top/ai/>（由 nginx Basic Auth 保护，凭据不写入仓库）。

项目最初基于理赔 Agent 培训材料，现已扩展为可本地运行、可容器化部署的多领域 RAG 应用。真实理赔仍需接入组织内的保单查询、单证核验、通知/支付等适配器；未配置时状态机会显式转人工，不返回假保单或虚构定损。

**当前验证基线（2026-10-27）**：`182 passed, 1 skipped`，覆盖率约 83%；跳过项为需要真实 Milvus 的集成测试。完整逐项映射见 [实现验收清单](docs/implementation-matrix.md)，架构见 [Architecture.md](Architecture.md)，Agent 工作约定见 [AGENTS.md](AGENTS.md)。

三条主链路：

```text
/api/assistant/stream  -> 意图路由（JEV/LLM/Hybrid）-> 理赔 / 投资 / 通用问答（SSE）
/api/claims/*          -> 理赔状态机（补材料、审核、恢复）
/api/rag/*             -> 通用知识库检索与引用校验
/api/investment/rag/*  -> 投资知识库只读检索
```

## 线上演示

- 地址：<https://aiwanxiang.top/ai/>；`/ai` 会 301 到 `/ai/`。
- 入口由 nginx Basic Auth 保护，`/ai/` 反向代理到 `127.0.0.1:8001`；应用不直接监听公网。
- 当前线上为单机部署：`app` 容器 + `embed` 容器（BGE-M3 / BGE-Reranker）+ Milvus Lite + SQLite。
- 当前线上仍使用 `APP_ENV=development` + nginx Basic Auth，仅适合演示/内测；生产模式必须同时配置 API 认证、限流、备份、监控，并更换默认弱口令。
- 部署、更新与回滚见下文「部署到 VPS：`/ai` 子路径」。

## ⚠️ 三个虚拟环境，先分清再动手

| 提示符 | 用途 | 里面有什么 |
| --- | --- | --- |
| `(.venv-py315)` | **主项目**：启动 Web 服务、跑测试、调用大模型 | FastAPI、uvicorn、LangChain 0.3 全家桶 |
| `(.venv-embed)` | **本地 BGE-M3 / BGE-Reranker 服务**（Python 3.12） | sentence-transformers、torch、FastAPI、uvicorn；主项目通过 HTTP 调用 |
| `(.venv-deep)` | 可选的官方 Deep Agents 隔离环境 | 只有 deepagents 及其依赖，**没有 uvicorn / FastAPI** |

> 运行版本：本地主环境使用 Python 3.15；app 镜像为 Python 3.14；embed 镜像为 Python 3.12；CI 当前覆盖 3.12/3.14。修改依赖或 Dockerfile 时需同时验证这些组合。

> `.venv-py314` 已废弃；需要 Deep Agents 时，用 Python 3.15 重建 `.venv-deep`（先确认 `deepagents` 支持 3.15）。`.venv-embed` 只在需要本地 embedding/rerank 时使用，未启动时 RAG 会自动降级为词项重排。

启动服务前，先确认提示符是 `(.venv-py315)`；如果不是，先切换。

PowerShell：

```powershell
deactivate
.\.venv-py315\Scripts\Activate.ps1
```

Git Bash：

```bash
deactivate
source .venv-py315/Scripts/activate
```

> 若执行 `uvicorn ...` 报「无法将 uvicorn 识别为 cmdlet」或 `command not found`，十有八九是当前激活成了 `.venv-deep` 或 `.venv-embed`。

> 激活提示符只显示目录名，多个目录下都叫 `.venv-py315` 时看起来完全一样。用 `which python`（Windows：`Get-Command python`）确认解释器在**本项目根目录**下；例如 `My_Study/Python/.venv-py315` 是学习目录的环境，里面没有 FastAPI/uvicorn。

## macOS 快速启动（Apple Silicon / Intel）

macOS 自带的 `/usr/bin/python3` 通常是 3.9.6，**低于项目要求的 3.12**；直接执行 `pip install -r requirements.txt` 会在 `numpy==2.5.3` / `pandas==3.0.6` 处报找不到匹配版本。先装 Python 3.15，再建虚拟环境。

最短路径（依赖已装好时）：

```bash
#查看端口是否被占用
lsof -ti tcp:8001 | xargs ps -o pid,ppid,command -p

cd /Users/Song/workspace/claims-ai-agent
bash scripts/set_deepseek_key.sh   # 首次：交互式写入 DeepSeek Key 并校验（不回显）
bash scripts/start_mac.sh          # 启动；任意目录执行都可以，自动切根目录 + 选 venv
# 打开 http://127.0.0.1:8001/
```

> **最容易踩的坑：同名 `.venv-py315`。** 仓库里 `My_Study/Python/` 也有一个学习用的 `.venv-py315`，激活后提示符一模一样，但里面只有 pytest/openai/rich/mypy 等，**没有 uvicorn/FastAPI**，于是报 `command not found: uvicorn`。启动前先自检：
>
> ```bash
> pwd              # 必须是 .../claims-ai-agent
> which python     # 必须是 .../claims-ai-agent/.venv-py315/bin/python
> which uvicorn    # 找不到就说明目录或环境不对
> ```

### 1. 安装 Python 3.15

uv（推荐，装到 `~/.local`，不需要 sudo）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.15
uv python find 3.15
```

若提示 `command not found: uv`，把安装目录加进 PATH（zsh）：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && source ~/.zshrc
```

Homebrew：

```bash
brew install python@3.15
# Apple Silicon: /opt/homebrew/bin/python3.15
# Intel:        /usr/local/bin/python3.15
```

也可以下载 python.org 的 macOS universal2 安装包，装完位于 `/usr/local/bin/python3.15`。

> 若 `python3.15` 不在 PATH，用完整路径建环境：`~/.local/bin/python3.15 -m venv .venv-py315`（uv 安装）或 `/opt/homebrew/bin/python3.15 -m venv .venv-py315`（Apple Silicon Homebrew）。

### 2. 创建虚拟环境并安装依赖

```bash
cd /Users/Song/workspace/claims-ai-agent
python3.15 -m venv .venv-py315
source .venv-py315/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip check
```

用 uv 建环境也可：`uv venv --seed --python 3.15 .venv-py315`。**不要漏 `--seed`**，否则环境里没有 pip（可改用 `uv pip install -r requirements.txt`）。

> 国内网络直连 pypi.org 容易超时（`ReadTimeoutError` / `NameResolutionError`），可换镜像：
> `python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt`。

说明：

- Apple Silicon 原生 arm64 解释器可直接安装 arm64 wheel，不需要 Rosetta，也不需要 Xcode 编译。
- `requirements.txt` 中 PyYAML 在 `python_version >= "3.15"` 时使用 `vendor/` 的纯 Python wheel（该标记对所有平台生效，不仅 Windows），功能一致，只是关闭 libyaml C 加速。
- 本项目 RAG 通过 `VECTOR_STORE_URI`（未设置时回退 `MILVUS_URI`）选择向量库：macOS/Linux 可指向本地 `./.data/milvus.db` 使用嵌入式 Milvus Lite（默认安装 `milvus-lite`），也可指向外部 Milvus；Windows 不安装 `milvus-lite`，需连接外部 Milvus。

### 3. 配置 .env（默认 local，可选 DeepSeek）

`.env.example` 默认 `MODEL_PROVIDER=local`，适合本机 Ollama / vLLM / LM Studio；如果使用 DeepSeek，推荐用脚本写入密钥，**不回显、不进 shell 历史**：

```bash
bash scripts/set_deepseek_key.sh
```

脚本会：创建 `.env`（若不存在）→ 提示输入 key → 设为 `MODEL_PROVIDER=deepseek` → `chmod 600` → 调 `GET /models` 校验鉴权，并检查 `DEEPSEEK_FLASH_MODEL` / `DEEPSEEK_PRO_MODEL` 是否在账号可用列表中。

手工配置 DeepSeek 等价于：

```bash
cp .env.example .env && chmod 600 .env
# 编辑 .env：
#   MODEL_PROVIDER=deepseek
#   DEEPSEEK_API_KEY=sk-...
```

> 选择 `deepseek` 但没填 key 时服务会**拒绝启动**，报 `DeepSeek模式需要配置DEEPSEEK_API_KEY`——这是配置校验，不是依赖问题。选择 `local` 时，需要先启动 `LOCAL_LLM_BASE_URL` 指向的 OpenAI 兼容推理服务。

其他可选 provider：

| 目的 | 配置 |
| --- | --- |
| DeepSeek：真实对话与单证识别 | `MODEL_PROVIDER=deepseek` + `DEEPSEEK_API_KEY` |
| 百炼 | `MODEL_PROVIDER=bailian` + `OPENAI_API_KEY` + `QWEN_*_MODEL` |
| 本机推理（Ollama / vLLM / LM Studio，需自备模型） | `MODEL_PROVIDER=local`，改 `LOCAL_LLM_BASE_URL` 并使 `LOCAL_*_MODEL` 与服务注册名一致 |
| 完全不接模型，只看演示 | 保持任意 provider，直接点页面「载入演示」；对话仍不可用 |

意图路由（可选；代码默认不改变现有行为）：

| 目的 | 配置 |
| --- | --- |
| 代码默认：LLM 主路由 + JEV 影子（只记录） | `INTENT_ROUTER_ENABLED=true`、`INTENT_ENGINE=shadow` |
| JEV 主路由 + LLM 兜底（当前 `.env`） | `INTENT_ENGINE=hybrid` + `JEV_API_KEY=...` |
| 只用 JEV / 只用 LLM | `INTENT_ENGINE=jev` / `INTENT_ENGINE=llm` |
| 关闭路由层，回到内置 LLM 分类 | `INTENT_ROUTER_ENABLED=false` |

> 当前仓库 `.env` 已配 `JEV_API_KEY` 并设 `INTENT_ENGINE=hybrid`（JEV 主 + LLM 兜底）。
> 没配 `JEV_API_KEY` 时影子会自动跳过，服务照常启动；`INTENT_ENGINE=jev/hybrid`
> 但缺 key 时主链路回落内置分类并记录 warning。JEV 是英文优先模型，中文场景可开
> `INTENT_TRANSLATE_TO_ENGLISH=true`。2026-10-27 评测：39 条样本联合准确率 89.7%。

改完自检：

```bash
python -c "from settings import Settings; s=Settings(); print(s.app_env, s.business_mode, s.model_provider)"
```

> `BUSINESS_MODE=demo` 只影响案件状态机与演示入口；对话链路仍要调用模型。完全不配模型时，只有「载入演示」、健康检查和状态机可用。

临时切成演示模式（macOS 的 BSD `sed` 需要 `-i ''`）：

```bash
sed -i '' 's/^BUSINESS_MODE=.*/BUSINESS_MODE=demo/' .env
```

### 4. 启动服务

**推荐用启动脚本**（任意目录执行都行，会自动切到项目根目录、挑选可用 venv，并默认开启热重载）：

```bash
bash /Users/Song/workspace/claims-ai-agent/scripts/start_mac.sh              # 默认 8001，热重载开
bash /Users/Song/workspace/claims-ai-agent/scripts/start_mac.sh 8002         # 换端口
bash /Users/Song/workspace/claims-ai-agent/scripts/start_mac.sh --no-reload  # 关闭热重载
```

手动启动时等价于：

```bash
source .venv-py315/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8001 --reload \
  --reload-exclude "$PWD/.venv-py315" \
  --reload-exclude "$PWD/.git" \
  --reload-exclude "$PWD/.data" \
  --reload-exclude "$PWD/My_Study"
```

不激活环境也可以直接调用：

```bash
.venv-py315/bin/uvicorn app:app --host 127.0.0.1 --port 8001 --reload
```

- 工作台：<http://127.0.0.1:8001/>
- 接口文档：<http://127.0.0.1:8001/docs>
- 检查点库：首次启动自动创建 `.data/checkpoints.sqlite`
- 审计库：首次启动自动创建 `.data/audit.sqlite`（只追加 + 哈希链）

**热重载说明**

- `--reload` 依赖 `watchfiles`（已写入 `requirements.txt`）。只有装了 watchfiles，`--reload-exclude` 才生效；否则 uvicorn 退化为 `StatReload`，会连 `.venv-py315` 里的几万个 `.py` 一起扫描。
- 排除目录必须传**绝对路径**：uvicorn 用 `exclude_dir in path.parents` 判断，相对路径不生效（本次已踩过）。
- 改代码后进程自动重启，`.data/checkpoints.sqlite` 在磁盘上，重启不丢案件状态；但**进行中的 SSE 请求会断开**，刷新页面重发即可。
- 不要加 `--workers`（示例按单进程设计，SQLite + 内存锁不支持多 worker）。
- 生产/演示验收建议 `--no-reload`，避免改文件导致服务抖动；Dockerfile 中默认即无 reload。

### 5. 验证

另开一个终端：

```bash
curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8001/ready
.venv-py315/bin/python -m scripts.audit_verify --limit 5
.venv-py315/bin/python health_check.py --url http://127.0.0.1:8001
.venv-py315/bin/python -m pytest -q
```

`health_check.py` 只提交一条缺保单号的合成报案，校验状态机进入 `awaiting_information`，不触发模型或真实业务，因此未配置模型也能通过。

也可一条命令跑完整验证（会占用 8001 端口）：

```bash
bash scripts/verify.sh                                  # 自动选择可用的主项目环境，通常为 .venv-py315
VENV_DIR=.venv-py315 bash scripts/verify.sh              # 或显式指定
```

> `verify.sh` 内部以**无 reload** 的固定进程启动，避免验证过程中因文件变动重启；日常开发用 `start_mac.sh` 即可。

### 6. 停止与排错

停止：`Ctrl+C`。端口被占用：

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN
kill <PID>
```

| 现象 | 原因与处理 |
| --- | --- |
| `No matching distribution found for numpy==2.5.3` | 用了系统 Python 3.9；按第 1、2 步重建 3.15 环境 |
| `command not found: uvicorn` | 没激活 `.venv-py315`，或误激活了不含 uvicorn 的 `.venv-deep` |
| `Address already in use` | 8001 被占用，`lsof` 后 kill，或改用 `--port 8002` |
| 启动时报缺少 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` | `.env` 里 provider 与 key 不匹配；运行 `bash scripts/set_deepseek_key.sh` 或手工补 key |
| 对话报 `APIConnectionError`（阶段 classification） | 当前 provider 的模型服务不可达：`local` 需 127.0.0.1:8000 有推理服务；`deepseek` 检查网络与 `DEEPSEEK_BASE_URL` |
| RAG 报连接失败且 `EMBEDDING_BASE_URL` 指向 8010 | 本地 BGE-M3 服务未启动；按「本地 BGE-M3 embedding」启动 `.venv-embed` 服务 |
| 对话报 `AuthenticationError` / HTTP 401 | DeepSeek key 无效或未生效；重新写入 key 后**重启**服务 |
| 页面能打开，对话返回 503 | 本地模型地址不可达或模型名不匹配；查看 uvicorn 日志与 trace |
| 单证识别 502/503 | 所选模型不支持多模态，或未按 JSON 返回 |
| 安装/运行时报架构错误 | 混用了 Rosetta（`arch -x86_64`）与 arm64 解释器；删除 venv 重建 |
| `xcrun: error` | `xcode-select --install`；绝大多数依赖有 wheel，一般用不到 |
| `ReadTimeoutError` / `NameResolutionError` / `from versions: none` | 访问 pypi.org 超时或被解析失败；改用国内镜像：`python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt` |
| 已激活 `(.venv-py315)` 但仍 `command not found: uvicorn` | 当前目录不是项目根目录。`My_Study/Python/` 下也有同名 `.venv-py315`（学习环境，无 FastAPI/uvicorn）；`pwd` 确认后 `cd` 回项目根目录，或用 `bash scripts/start_mac.sh` |
| 改代码后没有自动重启 | ① 未安装 `watchfiles`（`pip install -r requirements.txt`）；② 启动时带了 `--no-reload`；③ 改的是排除目录（`.venv*`、`.data`、`My_Study`）里的文件 |
| 一改代码就重启、CPU 很高 | `--reload-exclude` 未生效，通常是传了相对路径；改用 `scripts/start_mac.sh`，它传的是绝对路径 |

### 7. 可选：Docker

```bash
cp .env.example .env      # 已存在则跳过
docker compose up -d --build
```

Apple Silicon 上应用容器为 arm64。若 `--profile infra` 的 Milvus 拉不到 arm64 镜像，可对这些服务单独使用 `--platform linux/amd64`，或只启动 `app` 并指向外部 Milvus。

> 本机验证（macOS 14.8.2 / Apple Silicon / Python 3.15.1）：`pip check` 无冲突，`pytest` 为 **182 passed, 1 skipped**（跳过项需真实 Milvus），`uvicorn app:app` 启动后 `/health`、`health_check.py` 均通过。国内网络安装依赖时请使用上面的清华镜像。

## 结构与职责

```text
claims-ai-agent/
├── app.py                      # FastAPI 路由、lifespan、SSE、工作台接口
├── settings.py                 # Pydantic 环境配置与密钥校验
├── config.py                   # 模型工厂、缓存和任务参数
├── claims_agent.py             # 理赔端到端入口与离线演示
├── confidence_system.py        # 置信度公共入口
├── logging_setup.py            # 日志、请求 ID、轮转与脱敏
├── monitoring.py               # Prometheus 业务指标
├── health_check.py             # HTTP 健康与状态机验证
├── requirements.txt            # 主要依赖版本锁定（完整冻结见 requirements-py315.lock.txt）
├── .env.example                # 环境模板，不包含真实密钥
├── static/                     # 工作台前端（index.html / app.js / styles.css）
├── agents/                     # 接入层、对话/理赔编排、审计、可观测性
│   ├── http_middleware.py      # 请求 ID、认证、限流、审计、异常兜底
│   ├── claim_agent.py          # 理赔 LangGraph、Send 并行、HITL
│   ├── assistant_agent.py      # 对话助手 LangGraph 多节点编排
│   ├── investment_agent.py     # 投资域图与演示
│   ├── risk_agent.py           # 结构化专家意见与模型调用
│   ├── audit_store.py          # append-only + 哈希链审计
│   ├── middleware_audit.py     # 模型层：脱敏、限流、缓存、重试、审计
│   └── ...
├── tools/                      # 业务工具、RAG、Milvus、rerank、文档解析
│   ├── knowledge_rag.py        # 通用知识库多路召回 + RRF + rerank
│   ├── investment_rag.py       # 投资 Wiki RAG
│   ├── rag_retrieval.py        # 理赔条款检索与引用校验
│   ├── rerank.py               # BGE-Reranker HTTP 客户端与词项降级
│   ├── vector_store.py         # Milvus 集合与可达性检查
│   └── ...
├── adapters/                   # 真实业务适配器与 demo 后端
├── agent_core/intent/          # 意图路由（JEV/LLM/Hybrid）+ adapter 主链路接入点
├── data/
│   ├── investment_wiki/        # 投资知识库源文件（当前约 55 chunks）
│   ├── knowledge_base/         # 通用知识库源文件
│   └── intent_golden.jsonl     # 意图评测集
├── configs/                    # 领域与意图注册配置
├── docs/                       # 架构、RAG、结构化输出等文档
├── scripts/                    # 启动、构建索引、验证、embed 服务、VPS 部署
│   ├── embed_server.py         # BGE-M3 / Reranker HTTP 服务
│   ├── deploy_vps.sh           # 当前实际使用的 rsync + Compose 部署脚本
│   └── ...
├── tests/                      # 单元、状态机、HTTP、RAG 与可选 Milvus 集成测试
├── demos/                      # 参数/消息/本地接口/链路图演示
├── deploy/                     # 回归门禁、shadow、监控告警与运维手册
├── isolated_deep/              # 可选：官方 Deep Agents 独立依赖与运行时
├── vendor/                     # 3.15 下使用的纯 Python PyYAML wheel
├── Dockerfile                  # app 镜像（Python 3.14，非 root，单 worker）
├── Dockerfile.embed            # BGE-M3 / Reranker 镜像（Python 3.12）
├── docker-compose.yml          # 本地/开发 Compose（Redis/Milvus 可选 infra profile）
├── docker-compose.prod.yml     # 单机生产形态（app + embed，bind mount）
├── docker-compose.langfuse.yml # 可选：自托管 LangFuse
├── deploy.sh                   # 固定镜像版本发布与回退（模板流程）
└── .github/workflows/deploy.yml # CI；当前 push 仅 main 触发，deploy job 尚未与 rsync 流程对齐
```

agents/tools/prompts/models/tests及新增Python包均有`__init__.py`。

> 当前语料规模：投资 Wiki 约 55 个 chunk，通用知识库只有少量示例文档（约 3 个 chunk）；理赔条款语料尚未内置，真实理赔条款检索需要另行建库。

> `agent_core/` 原名 `platform/`，与标准库同名会遮蔽 `platform` 模块，导致 `coverage`、`setuptools` 等直接报 `module 'platform' has no attribute ...`。已重命名为 `agent_core/`，并同步更新 `scripts/eval_intent.py` 与 `tests/test_intent_*.py` 的导入；新增代码不要再用 `platform` 作为包名。

> 注：`My_Study/` 为个人学习测试目录，不属于本项目实现，可忽略。

> 分层组件图与各链路时序见 [demos/完整链路图.md](demos/完整链路图.md)；部署视图见 [demos/本地部署架构图.md](demos/本地部署架构图.md)。

## 对话助手链路的架构演进（方案 A → 方案 B）

链路① 对话助手（`/api/assistant/stream`）已从手写生成器重构为 LangGraph 多节点图（`agents/assistant_agent.py`）。分两阶段推进：

### 方案 A（已实现）：无状态多节点图

- 图节点：`classify`（IntentRouter 意图路由）→ 条件路由 → `policy_query` / `material_gate` → `follow_up` / `formal_review`
- 意图路由由 `app.py` 启动时构建一次（`build_assistant_intent_router`）；代码默认 `shadow`，
  当前 `.env` 为 `hybrid`：JEV 主路由 + LLM 兜底；路由异常时回落 `assistant_agent`
  内置分类模型，SSE 不中断
- 图负责编排决策，LLM 流式回答由外层执行器（`app.py` 的 `assistant_stream`）负责
- 无 checkpointer，每次请求新建图，状态仍由前端回传（history / material_round）
- 详细结构见 [Architecture.md](Architecture.md)，意图路由细节见
  [docs/platform-architecture-workflow.md](docs/platform-architecture-workflow.md)

### 方案 B（规划中）：有状态图 + 断点续跑

目标：让对话助手与链路② 理赔状态机架构完全统一，具备状态持久化、断点续跑与 HITL。

改造点：

1. **引入 checkpointer**：给 `build_assistant_graph` 接 `AsyncSqliteSaver`（复用 `.data/checkpoints.sqlite` 或独立库），对话状态、材料轮次存后端。
2. **材料回流改 interrupt**：当前 `material_round` 由前端回传；改为 `interrupt()` 挂起，前端从「传历史」变成 `Command(resume=...)` 恢复。
3. **保单查询反问改 interrupt**：缺保单号时 `interrupt` 挂起等用户补保单号，而不是一次性反问结束。
4. **恢复 token 级流式**：图内 LLM 节点改用 `graph.astream_events()`（`on_chat_model_stream`）捕获 token，替代当前「图外流式回答」，使回答也成为图节点。
5. **前端 state 管理**：从「前端保存 history/material_round」改为「后端 checkpointer 保存，前端只传 thread_id + resume」。
6. **测试迁移**：`FakeWorkbenchModel` 适配图流式回调，补充断点续跑用例。

完成后两条链路（对话助手、理赔状态机）共用同一套 LangGraph + checkpointer + interrupt 模式。

## 安装和离线验证（Windows；macOS 见上文「macOS 快速启动」）

在项目根目录执行。主项目最低 Python 3.12+，本地开发/测试使用 Python 3.15；app 容器为 Python 3.14，embed 容器为 Python 3.12。`requirements.txt` 为主依赖锁定，完整冻结见 `requirements-py315.lock.txt`。Windows 不安装 `milvus-lite`（仅支持 Linux/macOS），RAG 需连接外部 Milvus 服务；macOS/Linux 可改用本地 `./.data/milvus.db`。

3.15 适配要点：部分旧锁定版本没有 `cp315` Windows wheel，已做最小升级；`PyYAML 6.0.3` 官方无 `cp315` wheel，改用 `vendor/pyyaml-6.0.3-py3-none-any.whl`（纯 Python 构建，功能等价，仅关闭 libyaml C 加速），因此无需安装 Visual C++ 生成工具。

| 包 | 原版本 | 现版本 | 原因 |
| --- | --- | --- | --- |
| aiohttp | 3.14.3 | 3.14.4 | 无 cp315 wheel |
| markupsafe | 3.0.3 | 3.0.4 | 无 cp315 wheel |
| pandas | 2.3.3 | 3.0.6 | 2.3.x 无 cp315 wheel，最小可用为 3.0.6 |
| yarl | 1.24.5 | 1.25.1 | aiohttp 3.14.4 要求 `yarl>=1.25.1` |
| PyYAML | 6.0.3 | 6.0.3（纯 Python wheel） | 官方无 cp315 wheel，见 `vendor/` |
| ruff | 0.9.10 | 不变 | 自带 `py3-none-win_amd64` wheel |

> 验证结果：`pip check` 无依赖冲突；本轮测试集在 macOS 上为 **182 passed, 1 skipped**（跳过的是需要真实 Milvus 服务的集成用例），Windows 未在本轮复测。

Windows（PowerShell）：

```powershell
py -3.15 -m venv .venv-py315
.\.venv-py315\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip check
# 首次创建；已有.env不要覆盖。
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m pytest -q
python claims_agent.py --demo
python -m demos.module04_demo --prompts
python -m scripts.benchmark_parsers
```

Windows（Git Bash）：

```bash
python -m venv .venv-py315
source .venv-py315/Scripts/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
python -m pip check
# 首次创建；已有.env不要覆盖。
if [ ! -f .env ]; then cp .env.example .env; chmod 600 .env; fi
python -m pytest -q
python claims_agent.py --demo
python -m demos.module04_demo --prompts
python -m scripts.benchmark_parsers
```

Linux/macOS 只需把激活路径换成 `bin/`；macOS 完整步骤（含 Python 3.15 安装、演示模式与排错）见上文 [macOS 快速启动](#macos-快速启动apple-silicon--intel)：

```bash
python3.15 -m venv .venv-py315
source .venv-py315/bin/activate
python -m pip install -r requirements.txt
```

这些离线演示不代表真实模型、赔付系统或向量服务已联通。模型服务需支持OpenAI兼容聊天、JSON、tools；部分流式服务不返回usage，此时用量标记未知，不能声称零成本。固定seed只尽力复现。

## 启动HTTP服务

使用主项目环境 `.venv-py315`（不是 Deep Agents 的 `.venv-deep`，后者不含 FastAPI/uvicorn）。

PowerShell：

```powershell
.\.venv-py315\Scripts\Activate.ps1
uvicorn app:app --host 127.0.0.1 --port 8001
# 另一个终端；PowerShell 里 curl 是 Invoke-WebRequest 别名，需明确调用 curl.exe
curl.exe -fsS http://127.0.0.1:8001/health
python health_check.py
```

Git Bash：

```bash
source .venv-py315/Scripts/activate
uvicorn app:app --host 127.0.0.1 --port 8001
# 另一个终端
curl -fsS http://127.0.0.1:8001/health
python health_check.py
```

macOS / Linux：

```bash
source .venv-py315/bin/activate
uvicorn app:app --host 127.0.0.1 --port 8001 --reload
# 另一个终端
curl -fsS http://127.0.0.1:8001/health
python health_check.py --url http://127.0.0.1:8001
```

macOS 推荐直接用启动脚本（自动切到项目根目录、自动选 venv，默认开热重载并排除 `.venv*`/`.data`/`My_Study`）：

```bash
bash scripts/start_mac.sh              # 默认 8001，热重载开
bash scripts/start_mac.sh 8002         # 指定端口
bash scripts/start_mac.sh --no-reload  # 关闭热重载
```

若不激活环境，也可直接用主环境解释器启动：

```powershell
.\.venv-py315\Scripts\uvicorn.exe app:app --host 127.0.0.1 --port 8001
```

```bash
.venv-py315/bin/uvicorn app:app --host 127.0.0.1 --port 8001
```

启动后访问 `http://127.0.0.1:8001/` 使用智能业务助手。页面采用普通对话形式，支持理赔、投资和通用咨询，支持多轮意图识别、PDF/DOCX/文本抽取、图片视觉识别，以及结合识别结果的流式问答。点击“离线载入演示”可用固定合成案件运行完整状态机，查看报案、保单、三专家、置信度和决策链路；“真实理赔演示”会调用真实模型和内存条款跑判责 RAG，但不连接真实业务系统。两个入口都在生产环境自动禁用。页面右侧「调用链路 → 平台内核 → 领域意图路由」会显示实际引擎（JEV / LLM / 内置分类）、是否兜底和影子一致性，消息意图徽章也会带引擎标签；IntentRouter 读取最近 12 轮对话和上一轮意图（作为 active_domain 提示）：省略主语的追问继承当前主题，明确的新问题允许切换主题。材料审核会按附件类型核查保单信息、事故/出险证明和费用/损失凭证；缺失时保留累计附件并最多回流追问三轮，仍不完整则建议转人工，材料补齐后轮次清零并继续理赔链路。五类理赔意图进入理赔专用提示和合规约束；投资/一般咨询交给对应提示和通用基模回答。附件仅在请求内存中处理，不落盘；图片识别要求配置的模型支持 OpenAI 兼容多模态消息。

也可先停止8001端口的现有本项目服务，再运行`bash scripts/verify.sh`完成启动与pytest两条验证链路（`scripts/*.sh`为Bash脚本，Windows需在Git Bash或WSL中运行）。

| 路由 | 行为 |
| --- | --- |
| GET /health | 仅进程存活，不代表模型、embedding 或 reranker 可用 |
| GET /ready | 就绪探针：检查理赔图与审计库，未就绪返回 503；当前不检查 embedding/reranker |
| POST /api/claims/process | 创建审核工作流；缺保单号进入补材料中断 |
| POST /api/demo/claims/process | 用固定合成案件运行完整理赔状态机；仅非生产环境 |
| POST /api/demo/claims/process-live | 用真实模型 + 内存条款跑完整判责演示；仅非生产环境 |
| POST /api/demo/investment/process | 用固定合成组合运行投资域演示；仅非生产环境 |
| GET /api/claims/{claim_id} | 查询已持久化案件状态 |
| POST /api/claims/{claim_id}/supplement | 仅补材料阶段接受 policy_id |
| POST /api/claims/{claim_id}/review | X-Reviewer-Key 认证后恢复人工审核 |
| POST /api/investment/rag/search | 只读检索投资知识库，返回引用，不生成交易建议 |
| GET /api/rag/domains | 列出已配置的知识库 domain |
| POST /api/rag/search | 通用知识库多路召回 + RRF + rerank，返回 Top-K 片段和引用 |
| POST /api/rag/answer | 检索后生成答案，并校验 citation_ids 只能来自本轮结果 |
| POST /api/investment/process | 投资咨询/组合诊断；交易指令二次确认前暂停 |
| POST /api/investment/{request_id}/confirm | 交易二次确认，进入人工审批，不执行下单 |
| POST /api/investment/{request_id}/review | 审核员审批投资指令 |
| GET /metrics | Prometheus 格式指标（需要认证） |
| GET /docs | 自动生成的接口文档；生产环境建议关闭 |
| GET / | 智能业务工作台 |
| POST /api/documents/analyze | 内存解析并识别最多 6 份理赔单证 |
| POST /api/assistant/stream | 结合案件、单证和历史上下文的流式问答（理赔/投资/通用） |

请求支持 description 或 claim_text，以及可选 policy_id、amount。理赔返回的是审核建议，不执行支付。SQLite 检查点保存在 `.data/checkpoints.sqlite`，重启可恢复。拒赔需授权人工提供条款依据；低置信度、证据不足和大额转人工。生产必须配置 `CLAIMS_API_KEY` 和 `REVIEWER_API_KEY`；示例不支持多租户行级权限，也不能直接横向扩容。

## 接入层中间件（认证 / 限流 / 审计）

所有 HTTP 请求先经过一条纯 ASGI 管线（`agents/http_middleware.py`），新增路由自动继承，不需要在每个 handler 里重复实现：

```text
CORS → RequestID → 认证 → 请求体上限 → 限流 → 审计 → 业务处理 → 异常兜底
```

| 能力 | 行为 | 配置 |
| --- | --- | --- |
| 请求 ID | 接受合法 `X-Request-ID`（8–64 位 `[A-Za-z0-9._-]`），否则生成 UUID；响应头回传，日志与审计可串联 | — |
| 认证 | `/api/*` 除 `/api/demo/*` 外由接入层校验 `X-API-Key`（未配置时开发放行，生产启动即失败）；审核类接口另需 `X-Reviewer-Key` | `CLAIMS_API_KEY`、`REVIEWER_API_KEY` |
| 请求体上限 | 超过上限直接 413，不进入业务 | `HTTP_MAX_BODY_BYTES`（默认 64MB） |
| 限流 | 按「身份 + 来源 IP + 接口类别」分桶，流式与单证接口独立配额；超限返回 429 + `Retry-After` | `HTTP_RATE_LIMIT_PER_MINUTE`（1200）、`HTTP_STREAM_RATE_LIMIT_PER_MINUTE`（120）、`HTTP_DOCUMENT_RATE_LIMIT_PER_MINUTE`（120）、`HTTP_RATE_LIMIT_ENABLED` |
| 审计 | 每条业务请求落库：request_id、身份、状态码、耗时、脱敏入参、IP 哈希；RAG 请求额外记录 `details.retrieval`（各路命中、融合数、重排候选、降级标志、最终引用）；只追加 + 哈希链，可检测篡改 | `CLAIMS_AUDIT_DB`（默认 `.data/audit.sqlite`，测试用 `:memory:`） |
| 异常兜底 | 未处理异常返回 500 JSON + request_id，不返回堆栈；SSE 已开始输出时不重复写响应 | — |

审计脱敏在落库前统一执行：手机号、身份证、银行卡等替换为占位符。请求体只在 JSON 且不超过 64KB 时截取摘要，不落原始文件、不落 `X-API-Key`。

```bash
python -m scripts.audit_verify --limit 10   # 校验哈希链，退出码 0 = 完整
```

`/health` 只表示进程存活；`/ready` 额外检查理赔图与审计库可用，未就绪返回 503，适合作为 K8s readiness 或负载均衡摘流依据。

> 本中间件是**接入层**；三专家模型调用仍有独立的 `MiddlewareChain`（脱敏、按案限流、缓存、熔断重试、HITL 标记），两层分工见 [docs/platform-architecture-workflow.md](docs/platform-architecture-workflow.md) §2.3。
>
> 限流与审计当前是**单进程**实现（内存桶 + SQLite）。多副本部署前需把限流换 Redis、审计换 Postgres/ClickHouse + WORM；两者接口已隔离，替换不侵入业务代码。

## 本地模型与可选云端

`.env.example` 默认 `MODEL_PROVIDER=local`，使用 LOCAL_LLM_BASE_URL/API_KEY 和 LOCAL_FAST/MAIN/PRO/VISION_MODEL，名称必须与推理服务实际注册名一致。本地服务端口默认 8000，应用端口 8001。设置 `MODEL_PROVIDER=local` 时需自备模型（Ollama / vLLM / LM Studio）并先启动推理服务。

如果使用 DeepSeek，运行 `bash scripts/set_deepseek_key.sh` 写入并验证密钥；脚本会检查 key 是否有效、`DEEPSEEK_FLASH_MODEL`/`DEEPSEEK_PRO_MODEL` 是否在账号可用列表中。选择 `deepseek` 但未配置 `DEEPSEEK_API_KEY` 时，启动会因配置校验失败而拒绝启动。

设置MODEL_PROVIDER=bailian时使用OPENAI_BASE_URL/API_KEY及QWEN_*_MODEL；已有百炼密钥无需删除，但不会自动用于其他模式。三个qwen别名分别映射通用、强推理、轻量模型。

设置MODEL_PROVIDER=deepseek时使用DEEPSEEK_BASE_URL/API_KEY及DEEPSEEK_FLASH_MODEL/DEEPSEEK_PRO_MODEL；默认base_url为`https://api.deepseek.com`，flash映射通用/轻量/视觉档位，pro映射强推理档位。DeepSeek思考模式默认关闭（DEEPSEEK_THINKING=false），因为推理token计入max_tokens且会削弱确定性；需要更强推理时设为true。DeepSeek不提供embedding接口，RAG仍需单独配置EMBEDDING_*。

### 本地 BGE-M3 embedding + Reranker（当前已启用）

不想依赖云端 embedding 时，可以在本机运行 BGE-M3（568M 参数、1024 维，CPU 即可）。主项目环境是 Python 3.15，而 `torch` / `onnxruntime` 目前没有 cp315 wheel，因此**推理要单独用 Python 3.12 环境**；主项目只通过 HTTP 调用。同一个服务还提供 `/v1/rerank`，供 RAG 的 Cross-Encoder 精排使用。

当前开发机已下载 `models/bge-reranker-base`（safetensors 约 1.1GB），`/health` 返回 `reranker_available=true`，真实检索返回 `rerank_fallback=false`。以下命令用于新环境安装或升级；检索本身不依赖模型一定存在，缺失时会自动使用词项重排。命令在项目根目录、激活 `.venv-py315` 后执行（第 2 步的 `.venv-embed` 除外）。

```bash
# 1) 下载权重（国内推荐 ModelScope；跳过 onnx 可省 2GB+）
python -m pip install modelscope -i https://pypi.tuna.tsinghua.edu.cn/simple
modelscope download --model BAAI/bge-m3 --local-dir ./models/bge-m3 \
  --exclude 'onnx/*' 'imgs/*' '*.jpg' '*.webp'

# 或走 HuggingFace 镜像（镜像站不支持 Xet，必须关闭，否则容易卡住）
# pip install -U huggingface_hub
# HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
#   hf download BAAI/bge-m3 --local-dir ./models/bge-m3

# 1.1) 下载 BGE-Reranker（当前开发机已下载；新环境才需要执行）
# safetensors 约 1.1GB；仓库同时提供 pytorch_model.bin / model.onnx，忽略它们可少下约 2.2GB。
.venv-py315/bin/python -c "from modelscope import snapshot_download; \
snapshot_download('BAAI/bge-reranker-base', local_dir='models/bge-reranker-base', \
ignore_file_pattern=['pytorch_model.bin', '*.onnx'])"

# 2) 独立 Python 3.12 推理环境
uv python install 3.12
uv venv --python 3.12 .venv-embed
uv pip install --python .venv-embed/bin/python \
  sentence-transformers sentencepiece fastapi uvicorn

# 3) 启动 OpenAI 兼容的 /v1/embeddings 与 /v1/rerank 服务
.venv-embed/bin/uvicorn scripts.embed_server:app --host 127.0.0.1 --port 8010
```

> Windows 把 `.venv-embed/bin/` 换成 `.venv-embed\Scripts\`（例如 `.venv-embed\Scripts\uvicorn.exe`）；下载与虚拟环境步骤相同。

`.env` 对应改为：

```ini
EMBEDDING_BASE_URL=http://127.0.0.1:8010/v1
EMBEDDING_MODEL=bge-m3
EMBEDDING_API_KEY=local

# 多路召回 + rerank
RERANK_ENABLED=true
RERANK_BASE_URL=http://127.0.0.1:8010/v1
RERANK_MODEL=bge-reranker-base
RERANK_TIMEOUT=10.0
RERANK_TOP_N=20
RERANK_RETRY_COOLDOWN=60
```

验证：

```bash
curl -s http://127.0.0.1:8010/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"bge-m3","input":"机动车保险责任条款"}' \
  | python -c "import sys,json;print(len(json.load(sys.stdin)['data'][0]['embedding']))"
# 1024

curl -s http://127.0.0.1:8010/v1/rerank \
  -H 'Content-Type: application/json' \
  -d '{"query":"基金风险","documents":["基金有市场风险","今天天气很好"]}'
# 模型存在时返回 results；不存在时返回 503，主项目自动降级为词项重排

PYTHONPATH=. .venv-py315/bin/python demos/module05_demo.py --embed
# {'documents': 2, 'dimensions': [1024, 1024]}
```

说明：

- 服务端使用 `normalize_embeddings=True` 做 L2 归一化，与 `rag_retrieval.py` 的 Milvus `L2` 索引匹配。BGE-M3 是 **1024 维**，换 embedding 模型必须重建 `claims_*` collection，否则维度不匹配；`ClaimVectorStore` 默认 `drop_old=False`，不会自动清理。
- 服务加载本地权重时会强制离线（`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`）。否则 `transformers` 会尝试连接 `huggingface.co`，在无法访问该站点的网络下启动会卡数分钟。
- `models/bge-m3/`、`models/bge-reranker*/` 已加入 `.gitignore`，不会把模型权重提交进仓库。
- **BM25 不是 reranker**：BM25 负责词法召回；rerank 使用 BGE-Reranker（Cross-Encoder）对 `query + document` 成对打分。当前开发机 BGE-Reranker 已启用，正常检索返回 `retrieval.rerank_fallback=false`；服务不可用时才降级为词项重排并返回 `true`。
- 不想引入 Python 环境时，也可用 Ollama：`ollama pull bge-m3`，然后把 `EMBEDDING_BASE_URL` 指向 `http://127.0.0.1:11434/v1`。
- 以上已验证 embedding 与 BGE-Reranker 的 `/v1/rerank`；向量入库/检索需要 Milvus：本地 macOS/Linux 可直接用下一节的 Milvus Lite，生产用 standalone（见「追踪、基础设施及部署」）。本机验证组合：macOS arm64 + Python 3.12.15 + sentence-transformers 6.2.0 + torch 2.14.1，单条短文本约 0.5s、冷启动约 2s（不含首次下载）。

### 本地 Milvus Lite（可选，macOS/Linux）

Milvus standalone : Milvus Lite ≈ PostgreSQL : SQLite。Lite 把向量引擎嵌入 Python 进程，不需要 Docker / etcd / MinIO，适合单机开发；`ClaimVectorStore`、`InvestmentWikiVectorStore` 和通用 `KnowledgeVectorStore` 只换 `VECTOR_STORE_URI`，代码不用改。

```ini
VECTOR_STORE_URI=./.data/milvus.db
```

- 首次使用会自动创建 `.data/milvus.db/` 目录，后续启动直接复用。
- **单进程**：不要开多个 uvicorn worker，也不要同时运行两个应用实例写同一个 `.db`。
- **仅 macOS/Linux**：Windows 不支持 `milvus-lite`，继续用外部 Milvus，或把向量库指向独立服务。
- 切回 Docker/远程 Milvus：删除 `VECTOR_STORE_URI`，或设为 `http://127.0.0.1:19530`。
- **不要把 `.db` 路径写进 `MILVUS_URI`**：`pymilvus` 导入时会读取 `.env` 里的 `MILVUS_URI` 作为全局默认连接，本地路径会被判定为非法 URI；`VECTOR_STORE_URI` 才是应用实际使用的地址。
- 投资知识库的 `tools/investment_rag.py` 会把 `.db` 路径识别为本地库，跳过 TCP 探活；向量库不可用时降级为 BM25 + 元数据，Reranker 不可用时再降级为词项重排。
- 本机已验证：`pymilvus 2.6.9 + milvus-lite 3.2.2 + faiss-cpu 1.15.1 + pyarrow 26.0.0`，`ClaimVectorStore` 的 add / update / search / version 过滤 / drop 均正常；投资知识库 55 个 chunk 可建索引并重复 `upsert`。
- `IVF_FLAT + nlist=1024` 在 Lite 下可用；数据量很小时会出现 `clustering ... please provide at least ... training points` 警告，不影响结果，数据量上来后消失。追求更简单可把索引换成 `FLAT`。
- Lite 首次建连/搜索时可能打印 gRPC `fork` 或 `FD from fork parent` 日志，单进程开发环境可忽略。

### 通用知识库 RAG 快速开始

```bash
# 1) 把业务文档放进 data/knowledge_base/（支持 .md/.txt/.pdf/.docx/.html）
# 2) 构建通用知识库向量索引（embedding 服务需先启动）
python scripts/build_knowledge_rag.py --domain general

# 3) 启动应用
PYTHONPATH=. .venv-py315/bin/python -m uvicorn app:app --port 8001
```

检索：

```bash
curl -s http://127.0.0.1:8001/api/rag/search \
  -H 'Content-Type: application/json' \
  -d '{"domain":"general","question":"多路召回和 rerank 是什么？","top_k":3}'
```

回答：

```bash
curl -s http://127.0.0.1:8001/api/rag/answer \
  -H 'Content-Type: application/json' \
  -d '{"domain":"general","question":"多路召回和 rerank 是什么？","top_k":3}'
```

`retrieval` 字段会显示每一路命中数、融合候选数、实际重排候选数、是否 rerank、是否降级；同一请求的审计详情 `details.retrieval` 也会保存这些诊断。回答接口会校验 `citation_ids` 只能来自本轮检索结果。完整说明见 [docs/knowledge-rag.md](docs/knowledge-rag.md)。

## 业务、RAG与记忆接入

- `BusinessBackend(adapters={...})`注册组织内真实协议。保单HTTP实现来自材料；其余接口没有协议，必须显式注册，不能靠默认成功返回值闭环。
- `DemoBackend`仅提供材料里的固定教学案例。`claims_agent.py --demo`还使用明确标记的合成专家结果。未执行实际模型调用。
- 写工具只有服务端authorize核对案件、金额、收款方等参数后才入Outbox。通知也需要审批。消费者须向下游传递相同幂等键并对账。
- `load_documents`要求险种、版本、生效日期；`ClaimVectorStore`默认不删除旧集合。混合检索使用加权RRF，重排通过已核实的reranker函数注入。扫描PDF需另接OCR。
- 判责条款检索（RAG）：`WorkflowServices(backend, clause_retriever=...)` 注入 `build_clause_retriever(HybridRetriever(...), insurance_type=...)` 后，三专家判责会先检索适用条款注入 prompt，专家在 `clause_ids` 中引用；引用必须落在已检索条款内，否则拒绝。未配置或检索失败自动降级为无条款，不阻断判责。
- 投资知识库 RAG：`data/investment_wiki/` 存放公开投资者教育 Wiki；`tools/investment_rag.py` 复用通用知识库的 **BGE-M3 向量 + BM25 + 元数据** 三路召回与加权 RRF，再交给 BGE-Reranker 精排。投资咨询对话会先检索知识并注入 `[K1]` 引用；向量/rerank 服务不可用时自动降级。`POST /api/investment/rag/search` 可只读检索；`python scripts/build_investment_rag.py` 构建向量索引。详见 [docs/investment-rag.md](docs/investment-rag.md)。
- 通用知识库 RAG：`data/knowledge_base/` 支持 Markdown/TXT/PDF/DOCX/HTML，`tools/knowledge_rag.py` 实现 **dense + BM25 + 元数据三路召回 → 加权 RRF → BGE-Reranker → Top-K/LLM 回答**。接口：`POST /api/rag/search`（片段 + 引用 + 召回诊断）、`POST /api/rag/answer`（答案 + citation_ids 校验）、`GET /api/rag/domains`。`python scripts/build_knowledge_rag.py --domain general` 构建索引；模型/服务不可用时自动降级为词项重排。详见 [docs/knowledge-rag.md](docs/knowledge-rag.md)。
- `ClaimContextManager`可注入Redis客户端、摘要链和实体抽取器；Qwen需注入匹配模型的token_counter，默认cl100k_base只作教学计数，首次使用需准备tiktoken缓存。

## 当前状态与已知边界（2026-10-27）

**已具备**

- 理赔、投资、通用问答三条链路可运行，前端工作台支持对话、附件上传和链路可视化；
- 意图路由已接入 `/api/assistant/stream`：JEV / LLM / Hybrid / Shadow 可切换，默认影子模式；
- BGE-M3 + BGE-Reranker 已启用，正常检索返回 `rerank_fallback=false`；
- 索引已建成：`investment_wiki` 约 55 个 chunk，`knowledge_general` 约 3 个 chunk；
- `182 passed, 1 skipped`，覆盖率约 83%；审计哈希链、请求 ID、PII 脱敏和 RAG 诊断字段可用；
- 线上 `/ai/` 已通过 nginx Basic Auth 部署，`app` 容器只监听 `127.0.0.1:8001`。

**仍需完善**

- **JEV 已接管主路由（hybrid）**：主链路已接入，当前 `.env` 为 `INTENT_ENGINE=hybrid`
  （JEV 主 + LLM 兜底）；39 条评测集联合准确率 89.7%，领域 100%，
  残余错误集中在「组合诊断 ↔ 投资咨询」，扩充语料前不要切 `jev` 单引擎。

- **真实理赔闭环**：`BusinessBackend` 目前只内置 `query_policy`，`verify_claim_evidence` 需要显式注册适配器；`CORE_QUERY_URL` 为空时真实案件会安全降级为转人工。真实上线前需接保单、单证核验、通知/支付，并补契约测试。
- **理赔条款语料**：代码支持 `claims_<险种>` 集合与条款引用校验，但仓库没有内置真实条款语料，当前主要使用演示条款。
- **RAG 评测**：已有意图评测集，但缺少覆盖投资/通用/理赔的 golden QA、Recall@K/MRR/nDCG/引用准确率回归。
- **Reranker 就绪**：`scripts/embed_server.py` 只预加载 embedding，reranker 为懒加载；`/health` 在 reranker 未加载时仍可能返回 ok，首次检索会多几秒。
- **单机限制**：SQLite + Milvus Lite 只适合单进程；多副本前需换 Postgres/Redis + 远程 Milvus，并避免多进程写同一个 Lite 文件。
- **安全与运维**：线上仍是 `APP_ENV=development` + nginx Basic Auth；需要更换默认弱口令，补充 nginx 限流、SSH 密钥登录、Docker 日志轮转、`.data` 备份和外部监控。
- **CI/CD**：`.github/workflows/deploy.yml` 当前只在 `main` 的 push 触发；deploy job 仍假设“服务器 Git 仓库 + `deploy.sh`”，与当前 `scripts/deploy_vps.sh` 的 rsync 流程不一致，需要二选一统一。

## 部署到 VPS：`/ai` 子路径（已验证）

下面这套方式适合单机 VPS：FastAPI 在容器内监听 `127.0.0.1:8001`，Embedding / Reranker 在独立容器内监听 `8010`，nginx 把 `/ai/` 反代到应用根路径。静态资源使用相对路径，因此同一份前端既能在本地 `/` 工作，也能在线上 `/ai/` 工作。

### 1. 目录与依赖

```text
/opt/claims-ai-agent/
├── app/                     # 代码（或直接把仓库放在这里）
├── data/                    # 知识库源文件，只读挂载
├── .data/                   # Milvus Lite、SQLite、日志，持久化
├── models/
│   ├── bge-m3/              # 约 2.1GB
│   └── bge-reranker-base/   # 约 1.1GB，model.safetensors
├── .env                     # 不放仓库，权限 600
├── Dockerfile
├── Dockerfile.embed
└── docker-compose.prod.yml
```

服务器需要 Docker 和 Compose v2。3.6GB 内存 + 2 核 CPU 的机器在同时加载 BGE-M3 和 Reranker 时建议增加 4GB swap；swap 只是防止 OOM，不会让 CPU 推理变快。

```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

### 2. 下载模型

模型不进入 Git，也不进入应用镜像。服务器能访问 Hugging Face 时，用独立容器下载：

```bash
docker run --rm \
  -v /opt/claims-ai-agent/models:/models \
  -v /opt/claims-ai-agent/scripts:/scripts \
  -e MODEL_DIR=/models \
  python:3.12-slim \
  sh -c 'pip install -q huggingface_hub && python /scripts/download_models.py'
```

下载脚本会跳过 `onnx/`、图片和重复权重，只保留 `pytorch_model.bin` / `model.safetensors` 与 tokenizer、config、Pooling 文件。

### 3. 配置 `.env`

从本地复制 `.env` 到服务器后执行 `chmod 600`。与本地开发不同的关键项：

```ini
APP_ENV=development
CLAIMS_API_KEY=
REVIEWER_API_KEY=
EMBEDDING_BASE_URL=http://embed:8010/v1
RERANK_BASE_URL=http://embed:8010/v1
RERANK_ENABLED=true
VECTOR_STORE_URI=/app/.data/milvus.db
LOG_FILE=/app/.data/logs/app.log
```

前端当前不发送 `X-API-Key`，所以公网访问不要直接使用 `APP_ENV=production`，否则页面会收到 401。公网保护由 nginx Basic Auth 承担；如果以后改成生产模式，需要同时给前端加 API Key 注入或改用服务端会话。

### 4. 构建与启动

```bash
cd /opt/claims-ai-agent
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

首次启动后构建两个索引：

```bash
docker compose -f docker-compose.prod.yml exec app python scripts/build_investment_rag.py
docker compose -f docker-compose.prod.yml exec app python scripts/build_knowledge_rag.py --domain general
docker compose -f docker-compose.prod.yml restart app
```

`docker-compose.prod.yml` 使用 bind mount 持久化 `.data/`，因此 Milvus Lite 和 SQLite 不会随容器删除而丢失。不要把同一个 `.data/milvus.db` 同时交给多个应用进程写。

### 5. nginx 反代与 Basic Auth

`/ai` 无尾斜杠时先 301 到 `/ai/`；`/ai/` 去掉前缀后转给应用的 `/`。SSE 必须关闭 buffering。

```nginx
location = /ai {
    return 301 /ai/;
}

location /ai/ {
    auth_basic "Claims AI";
    auth_basic_user_file /etc/nginx/.htpasswd-ai;
    client_max_body_size 80m;
    proxy_pass http://127.0.0.1:8001/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    # 不把 Basic Auth 凭据透传给应用
    proxy_set_header Authorization "";
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    chunked_transfer_encoding on;
}
```

生成密码文件：

```bash
# 用户名 admin；密码自行替换
printf 'admin:%s\n' "$(openssl passwd -apr1 '替换成强密码')" > /etc/nginx/.htpasswd-ai
chown root:nginx /etc/nginx/.htpasswd-ai
chmod 640 /etc/nginx/.htpasswd-ai
nginx -t && systemctl reload nginx
```

如果 HTTP 也配置了 `/ai/`，建议直接 301 到 HTTPS，避免 Basic Auth 凭据走明文：

```nginx
location = /ai { return 301 https://$host/ai/; }
location /ai/ { return 301 https://$host$request_uri; }
```

### 6. 开机自启

容器已设置 `restart: unless-stopped`。如需在 Docker 启动后统一拉起 compose，可加一个 oneshot 服务：

```ini
[Unit]
Description=Claims AI Agent (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/claims-ai-agent
ExecStart=/usr/bin/docker compose -f /opt/claims-ai-agent/docker-compose.prod.yml up -d --no-build
ExecStop=/usr/bin/docker compose -f /opt/claims-ai-agent/docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

### 7. 验证

```bash
curl -sS http://127.0.0.1:8001/health
curl -sS http://127.0.0.1:8001/ready
curl -sS -u 'admin:密码' https://你的域名/ai/health
curl -sS -u 'admin:密码' -X POST https://你的域名/ai/api/rag/search \
  -H 'Content-Type: application/json' \
  -d '{"domain":"general","question":"多路召回和 rerank 是什么？","top_k":2}'
```

检索结果里应看到 `vector_ready=true`、`reranked=true`、`rerank_fallback=false`；如果 `rerank_fallback=true`，先检查 `8010/v1/rerank` 和 `models/bge-reranker-base` 是否完整。`/ai` 只验证页面和 API 通不通时，不要用 `HEAD`，FastAPI 根路由只接受 `GET`。

### 8. 日常代码更新

服务器上没有 Git，代码由本地 `rsync` 推上去；`.env`、`.data/`、`models/` 权重都保留在服务器，不会被覆盖。

默认流程：

```bash
# 在本地仓库根目录
./scripts/deploy_vps.sh
```

脚本会依次执行：

1. 本地 `pytest -q`（不想跑可加 `SKIP_TESTS=1`）；
2. `rsync` 代码，排除 `.env`、`.data`、虚拟环境、`models/bge-*` 权重；
3. 服务器 `docker compose build app embed`；
4. 重建 `app` 容器，等待 `/health`、`/ready`；
5. 输出完成地址。

只改前端 `static/` 时，可以走更快的路径（`static/` 已 bind mount 到容器）：

```bash
./scripts/deploy_vps.sh --static-only
```

#### 手动等价命令

```bash
# 1) 同步代码；注意保留服务器上的 .env/.data/models 权重
rsync -az \
  --exclude '.git' --exclude '.env' --exclude '.data' \
  --exclude '.venv*' --exclude '__pycache__' \
  --exclude 'models/bge-m3' --exclude 'models/bge-reranker-base' \
  ./ vps:/opt/claims-ai-agent/

# 2) 重建并重启
ssh vps 'cd /opt/claims-ai-agent && \
  docker compose -f docker-compose.prod.yml build app embed && \
  docker compose -f docker-compose.prod.yml up -d --no-build embed && \
  docker compose -f docker-compose.prod.yml up -d --no-build --force-recreate app'

# 3) 验证
ssh vps 'curl -fsS http://127.0.0.1:8001/health && echo && \
  curl -fsS http://127.0.0.1:8001/ready'
```

#### 不同改动对应什么操作

| 改动 | 操作 |
| --- | --- |
| `app.py`、`agents/`、`tools/`、`models/*.py`、`prompts/` | 重建 `app` 镜像并重启 `app` |
| `static/` | 只同步 `static/`，无需重启（bind mount） |
| `requirements.txt`、`Dockerfile` | 重建 `app` 镜像；依赖层会重新安装 |
| `scripts/embed_server.py`、`Dockerfile.embed` | 重建 `embed` 镜像并重启 `embed`，再重启 `app` |
| `.env` | 不改镜像，`docker compose up -d --force-recreate app` 让新环境变量生效 |
| `data/investment_wiki/`、`data/knowledge_base/` | bind mount 已生效；需要重建索引并重启 `app` |
| `docker-compose.prod.yml` | `docker compose up -d --force-recreate app`；镜像构建配置变了才需要 build |
| nginx 配置 | 在服务器 `nginx -t && systemctl reload nginx`，与容器无关 |

知识库更新：

```bash
ssh vps 'cd /opt/claims-ai-agent && \
  docker compose -f docker-compose.prod.yml exec app python scripts/build_investment_rag.py && \
  docker compose -f docker-compose.prod.yml exec app python scripts/build_knowledge_rag.py --domain general && \
  docker compose -f docker-compose.prod.yml restart app'
```

如果修改了切块规则，先删除对应 collection 再重建，否则旧 chunk 会残留；详见 `AGENTS.md` 的“索引重建”。

#### 回滚

重建前先给当前镜像打备份 tag：

```bash
ssh vps 'docker tag claims-agent:prod claims-agent:backup-$(date +%Y%m%d%H%M)'
```

回滚时把备份 tag 重新指向 `claims-agent:prod`，再强制重建 `app`：

```bash
ssh vps 'docker tag claims-agent:backup-202610261200 claims-agent:prod && \
  cd /opt/claims-ai-agent && \
  docker compose -f docker-compose.prod.yml up -d --no-build --force-recreate app'
```

## 追踪、基础设施及部署

```bash
# 需要Docker；未装Docker的机器不能执行以下联调。
docker compose --profile infra up -d --wait etcd minio milvus redis
RUN_MILVUS_TESTS=1 python -m pytest -q tests/test_milvus_integration.py
# 配置LangFuse数据库密码、认证secret和salt后：
docker compose -f docker-compose.langfuse.yml up -d
# 在控制台创建项目、填写.env里的public/secret key并开启LANGFUSE_ENABLED后：
python -m demos.langfuse_demo --invoke
```

LangSmith演示已移除，自动追踪关闭；`langsmith`包仍是LangChain 0.3强制传递依赖，不能删除后还宣称依赖兼容。Deep Agents使用独立环境及LangFuse v3，详见`isolated_deep/README.md`。

上线前运行固定历史数据集门禁：`python -m deploy.regression_gate metrics.json --cost-budget 实际预算`。CI的自动部署默认关闭，须配置生产环境审批、SSH信任、固定镜像和目标检出版本后启用。部署操作和真实业务通知均未在此次实现中执行。
