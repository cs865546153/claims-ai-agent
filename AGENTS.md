# AGENTS.md

本文件是项目级的 Agent 工作说明。根目录使用 `AGENTS.md`（复数、全大写）是通用约定；
`My_Study/Agent 相关.md` 等学习笔记不作为执行规范。

## 项目定位

理赔智能助手 + 投资知识库 RAG + 通用知识库 RAG。

核心链路：

```text
FastAPI
  → 接入层（RequestID / 认证 / 限流 / 审计）
  → 意图识别
  → 理赔状态机 / 投资问答 / 通用问答
  → 多路召回 → RRF → BGE-Reranker → Top-K → 引用校验
  → LLM 流式回答
```

## 环境

- 主环境：`.venv-py315`
- Embedding / Reranker 服务：`.venv-embed`
- Python：3.15.x
- 本地向量库：Milvus Lite，`.data/milvus.db`（macOS/Linux）
- 远程/容器向量库：`MILVUS_URI=http://127.0.0.1:19530`

常用命令：

```bash
source .venv-py315/bin/activate
bash scripts/start_mac.sh

curl -fsS http://127.0.0.1:8001/health
curl -fsS http://127.0.0.1:8001/ready
```

Embedding / Reranker 服务：

```bash
.venv-embed/bin/uvicorn scripts.embed_server:app \
  --host 127.0.0.1 --port 8010
```

## 目录

```text
app.py                 FastAPI 路由、lifespan、工作台接口
agents/                理赔/投资编排、接入中间件、审计、可观测性
tools/                 RAG、Milvus、rerank、文档解析、知识库
data/investment_wiki/  投资 Wiki 源文件
data/knowledge_base/   通用知识库源文件
scripts/               启动、构建索引、验证、embed 服务
docs/                  架构、RAG、结构化输出等说明
tests/                 pytest 测试
.data/                 运行期数据，已 gitignore
```

## 启动与日志

推荐：

```bash
bash scripts/start_mac.sh
```

日志位置：

```text
.data/logs/app.log        # 应用日志，含 rag.retrieval
.data/logs/uvicorn.log    # uvicorn 启动/访问/异常日志
.data/audit.sqlite        # 审计库，含 details.retrieval
```

日志配置：

```dotenv
LOG_LEVEL=INFO
LOG_FILE=.data/logs/app.log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
# LOG_JSON=true
```

约定：

- `LOG_FILE` 父目录自动创建。
- 使用 `RotatingFileHandler`，默认 10MB × 5。
- `LOG_MAX_BYTES=0` 关闭轮转。
- 日志文件不可写时退回 stderr，不阻断启动。
- `.env` 修改后必须重启 uvicorn。
- 不要把日志只写到容器文件系统；容器环境优先 stdout/stderr + `LOG_JSON=true`。

查看：

```bash
tail -f .data/logs/app.log
tail -f .data/logs/uvicorn.log
grep 'rag.retrieval' .data/logs/app.log
```

## RAG 约定

### 通用 / 投资知识库

- 使用共享 `split_markdown_sections()` 切分 Markdown。
- 文件标题、免责声明合并到第一个 `##` 章节，不单独成块。
- `参考资料 / 参考来源 / 参考文献 / 延伸阅读 / 相关链接` 章节不进入索引。
- 纯风险提示/短免责声明块会被过滤。
- 投资 RAG 三路召回权重：`dense=0.55`、`bm25=0.30`、`metadata=0.15`，RRF `k=60`。
- `RERANK_TOP_N` 是进入 BGE-Reranker 的候选池上限；实际候选数为
  `min(fused_count, RERANK_TOP_N)`，并至少保留 Top-K。
- BGE 不可用时自动降级为词项重排，`rerank_fallback=true`。
- 检索诊断字段：
  - `route_hits`
  - `route_errors`
  - `fused_count`
  - `rerank_candidates`
  - `rerank_top_n`
  - `reranked`
  - `rerank_fallback`
  - `rerank_error`
  - `returned`
- 每次检索同时：
  - 写入结构化 `rag.retrieval` 日志；
  - 追加到审计 `details.retrieval`；
  - 返回 `retrieval` 给 API。

### 索引重建

```bash
python scripts/build_investment_rag.py
python scripts/build_knowledge_rag.py --domain general
```

注意：

- 修改切块规则会改变 `doc_id`。
- `upsert` 只覆盖同 ID 记录，不会删除旧 chunk。
- 切块规则变化后，先删除对应 collection 再重建：
  - `investment_wiki`
  - `knowledge_general`
- 否则 dense 召回仍可能命中旧标题块或参考资料块。

### 理赔 RAG

- 理赔条款使用独立集合 `claims_<insurance_type>`。
- 默认 `drop_old=False`，不要随意自动清空。
- 修改理赔检索行为时必须跑相关测试，不要影响投资/通用 RAG。

### 当前验证基线（2026-10-26）

`POST /api/assistant/stream`，问题 `投资基础知识`：

```text
intent=投资咨询
corpus_size=55
route_hits={dense:16, bm25:16, metadata:16}
route_errors={}
fused_count=27
rerank_candidates=20
reranked=true
rerank_fallback=false
returned=4
```

- citations：`K1` 投资基础/1、`K2` 合规边界/5、`K3` 流动性/5、`K4` 核实平台和人员/3。
- 回答引用 `[K1]`～`[K4]` 全部属于本轮检索结果，无非法引用。
- 总耗时约 12.8s；分类约 1.0s，投资回答生成约 6.7s。
- 宽泛问题下 K2/K4 偏合规/防诈骗，但回答用于风险提示和平台核实，属于可接受结果。

### 本地 / 远程 Milvus

- 本地 Lite：`VECTOR_STORE_URI=./.data/milvus.db`。
- 远程：删除 `VECTOR_STORE_URI` 或设为 HTTP 地址。
- 不要把 `.db` 路径写进 `MILVUS_URI`。
- 同一个 `.data/milvus.db` 只允许一个进程写；不要开多个 uvicorn worker。
- 本地开发重启服务前，先检查 8001 是否被占用：

```bash
lsof -nP -iTCP:8001 -sTCP:LISTEN
```

## 测试与质量

```bash
# 全量
.venv-py315/bin/python -m pytest -q

# 指定模块
.venv-py315/bin/python -m pytest -q \
  tests/test_knowledge_rag.py \
  tests/test_investment_rag.py \
  tests/test_logging_setup.py

# Ruff
.venv-py315/bin/python -m ruff check <changed-files>
```

当前基线（2026-10-26）：

- 全量测试：`174 passed, 1 skipped`
- 跳过项：`tests/test_milvus_integration.py`，需要真实 Milvus
- 已知无害日志：测试结束时 `milvus_lite` 可能打印
  `ValueError: I/O operation on closed file`，不影响结果
- Ruff：`line-length=110`

## 修改约定

- 不要主动 commit / push，除非用户明确要求。
- 不要删除或覆盖不认识的未提交改动。
- 不要提交 `.env`、`.data/`、`models/bge-*`、虚拟环境、密钥。
- 日志和审计中的输入输出必须经过 `mask_pii`；不要把密钥、手机号、身份证、银行卡写入日志。
- 修改行为、配置、接口、RAG 链路时，同步更新以下文档：
  - `README.md`
  - `Architecture.md`
  - `docs/knowledge-rag.md`
  - `docs/investment-rag.md`
  - `.env.example`
- 保持现有代码风格：Python 类型标注、中文注释/文档、Ruff 通过。
- 涉及运行期行为时，除了单元测试，尽量用真实 `/health`、`/ready`、`/api/.../search` 验证。
- 重启用户正在使用的 uvicorn 前先确认端口和进程；不要直接 `kill -9`。

## 关键文档

- `README.md`：安装、启动、接口、配置
- `Architecture.md`：整体架构
- `docs/knowledge-rag.md`：通用 RAG、rerank、审计诊断
- `docs/investment-rag.md`：投资 Wiki、索引构建、降级策略
- `docs/platform-architecture-workflow.md`：平台架构与工作流
- `docs/structured-output.md`：结构化输出约束
