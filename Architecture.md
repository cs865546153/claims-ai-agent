# 智能业务助手（Claims AI Agent）架构

> 理赔 + 投资 + 通用知识库 RAG

本文按当前代码整理，覆盖接入层、三条业务链路、RAG、意图路由、模型档位和运行期数据。
启动与接口示例见 `README.md`，Agent 工作约定见 `AGENTS.md`。

## 一、全景分层架构

```text
【前端层】 static/ 工作台
  聊天 / 单证上传 / 理赔与投资演示 / 调用链路可视化
       |
       v   HTTP / SSE
【接入层】 EnterpriseHttpMiddleware（纯 ASGI，每个 HTTP 请求）
  CORS -> RequestID -> 认证 -> 体积上限 -> 限流 -> 审计 -> 500 兜底
  认证：/api/* 校验 X-API-Key；生产启动强制配置密钥
  限流：身份 + IP + 接口类别（进程内；多副本需 Redis）
  审计：脱敏入参 + RAG 检索诊断写入 audit.sqlite，只追加 + 哈希链
       |
       v
【路由层】 app.py (FastAPI) —— 纯 URL 静态匹配，无大模型
  /api/assistant/stream                     -> 对话图（链路①）
  /api/claims/*                             -> 理赔状态机（链路②）
  /api/investment/*                         -> 投资域图（链路③）
  /api/rag/* · /api/investment/rag/search   -> 知识库检索 / 回答
  /api/documents/analyze                    -> 单证识别
  /api/demo/*                               -> 合成数据演示
  /health · /ready · /metrics               -> 存活 / 就绪 / 指标
       |
       v
【编排层】
  链路① 对话助手(LangGraph，无 checkpointer)
    classify(IntentRouter: JEV/LLM/Hybrid)
      -> general / investment_rag / investment_trade / policy_query
      -> material_gate -> follow_up 或 formal_review
  链路② 理赔状态机(LangGraph，SQLite checkpointer)
    intake -> policy -> experts(Send 三专家) -> route_decision
      -> auto / review / investigate
  链路③ 投资域图(LangGraph，SQLite checkpointer)
    intake -> context -> risk -> review / advise -> execute / rejected / terminal
  RAG
    投资 Wiki · 通用知识库 · 理赔条款
  工具 / 规划（未接主 app）
    AgentExecutor、Plan-and-Execute、RunnableWithMessageHistory
       |
       v
【服务层】
  WorkflowServices（保单 / 证据核验 / 三专家 + clause_retriever）
  InvestmentServices（组合 / 产品 / 行情 / 交易适配器）
  KnowledgeRAG / InvestmentRAG / HybridRetriever
  MiddlewareChain（专家调用：限流 -> 脱敏 -> 缓存 -> 推理 -> 降级 -> 审计 -> HITL）
       |
       v
【适配器层】
  BusinessBackend -> CoreSystemAdapter（HTTP + 熔断 + 只读缓存）-> 核心系统
  DemoBackend     -> PolicyStore（SQLite: policies.sqlite）
  InvestmentBackend -> 已注册的券商 / 基金 / 行情适配器（当前未接真实下单）
  DemoInvestmentBackend -> 固定合成组合、产品和行情
       |
       v
【模型层】
  flash（分类 / 轻量 / 降级）· plus（通用 / 客服 / 主专家）
  max（责任专家 / 强推理）· vision（单证视觉）
  JEV（远程意图分类，ateve-jev-v1，英文优先）
       |
       v
【数据层】
  SQLite : checkpoints.sqlite（理赔 / 投资图检查点）
           audit.sqlite     （接入层审计，只追加 + 哈希链）
           policies.sqlite  （本地模拟保单）
           outbox.sqlite    （回写队列；组件已实现，主图未注入）
  Milvus : claims_<insurance_type> / investment_wiki / knowledge_general
  Redis  : 会话历史（可选）
  日志   : .data/logs/app.log · .data/logs/uvicorn.log
```

横切能力包括 RequestID、API Key / 审核员认证、限流、PII 脱敏、审计哈希链、
Prometheus 指标、LangFuse（可选）和 SSE 流式输出。

## 二、生产部署形态（单机）

```text
公网
  |-- 443 nginx
  |     |-- /study/              -> 静态学习站
  |     |-- /                    -> trojan-web 面板
  |     `-- /ai/  (Basic Auth)   -> 127.0.0.1:8001
  |                                  app 容器（FastAPI / SSE）
  |                                  `-- http://embed:8010/v1
  |                                        embedding / reranker 容器
  |-- 444 trojan
  `-- 22  SSH
```

- 应用不监听公网，只绑定 `127.0.0.1:8001`；nginx 负责 TLS、Basic Auth、上传体积和 SSE 不缓冲。
- `/ai/` 反向代理时去掉前缀：`/ai/api/... -> /api/...`、`/ai/static/... -> /static/...`。
  前端资源和 API 使用相对路径，因此本地 `/` 和线上 `/ai/` 共用一份代码。
- BGE-M3 与 BGE-Reranker 放在独立 `embed` 容器，模型以只读 bind mount 挂载；
  应用和模型服务共享 Compose 网络。
- `.data/` 使用 bind mount 持久化 Milvus Lite、审计库、检查点和日志。
  不要多进程写同一个 Milvus Lite 文件。
- 实际发布脚本是 `scripts/deploy_vps.sh`（rsync + Compose），不是根目录 `deploy.sh`。
- 当前前端不发送 `X-API-Key`，公网入口使用 `APP_ENV=development` + nginx Basic Auth；
  若要切到 `APP_ENV=production`，必须同时解决前端密钥注入和审核员密钥管理。

## 三、入口路由

HTTP 层只做 URL 匹配，不做模型判断；真正的意图判断只发生在
`/api/assistant/stream` 的 `classify` 节点。

| 路由 | 认证 | 去向 |
|---|---|---|
| `GET /health` | 无 | 存活探针 |
| `GET /ready` | 无 | 就绪探针（图 + 审计库），未就绪返回 503 |
| `GET /metrics` | `X-API-Key` | Prometheus 指标 |
| `GET /` | 无 | 工作台页面 |
| `POST /api/assistant/stream` | `X-API-Key` | 对话图，SSE 流式 |
| `POST /api/documents/analyze` | `X-API-Key` | 单证识别，1–6 个附件，内存处理 |
| `POST /api/claims/process` | `X-API-Key` | 发起理赔案件 |
| `GET /api/claims/{claim_id}` | `X-API-Key` | 查询案件状态 |
| `POST /api/claims/{claim_id}/supplement` | `X-API-Key` | 补材料并恢复图 |
| `POST /api/claims/{claim_id}/review` | `X-API-Key` + `X-Reviewer-Key` | 人工审核；拒赔必须给条款依据 |
| `POST /api/investment/process` | `X-API-Key` | 投资咨询 / 组合诊断 / 交易指令 |
| `POST /api/investment/{request_id}/confirm` | `X-API-Key` | 交易二次确认 |
| `POST /api/investment/{request_id}/review` | `X-API-Key` + `X-Reviewer-Key` | 人工审批，未接真实下单 |
| `POST /api/investment/rag/search` | `X-API-Key` | 投资知识库只读检索 |
| `GET /api/rag/domains` | `X-API-Key` | 列出知识库 domain |
| `POST /api/rag/search` | `X-API-Key` | 通用知识库检索 |
| `POST /api/rag/answer` | `X-API-Key` | 检索 + LLM 回答 + 引用校验 |
| `POST /api/demo/claims/process` | 无 | 本地演示，生产返回 404 |
| `POST /api/demo/claims/process-live` | 无 | 演示 + 真实模型链路，生产返回 404 |
| `POST /api/demo/investment/process` | 无 | 投资演示，生产返回 404 |

路由分流关系：

```text
/api/assistant/stream -> 对话图 -> IntentRouter -> 业务节点
/api/claims/*         -> 直接进入理赔状态机（无意图路由）
/api/investment/*     -> 直接进入投资域图（intent 由请求字段显式给出）
/api/rag/*            -> 直接进入知识库检索 / 回答（无意图路由）
```

`/api/investment/process` 的 `intent` 是请求契约的一部分，不由对话图重新分类。
对话链路中的交易指令只做安全拦截，正式交易流程走 `/api/investment/*` 的
二次确认 + 人工审批。

## 四、链路① 对话助手（`/api/assistant/stream`）

实现：`agents/assistant_agent.py`。方案 A：无状态多节点图，图只做编排；
LLM 流式回答由 `app.py` 的外层执行器负责，以保留 token 级 SSE。

```text
START
  -> classify（IntentRouter：JEV/LLM/Hybrid；代码默认 shadow，当前 .env 为 hybrid）
  -> 条件路由 route_after_classify
       |-- 一般咨询  -> END（外层流式 general 回答）
       |-- 投资意图  -> investment RAG -> END（外层流式 investment 回答）
       |-- 交易指令  -> investment_trade -> END（只拦截，不下单）
       |-- 保单查询  -> policy_query -> END（反问保单号 / 输出保单摘要）
       |-- 其他理赔  -> material_gate
                          |-- 缺材料 -> follow_up -> END（最多 3 轮，超限转人工）
                          |-- 材料齐 -> formal_review -> END（三专家 + RAG 判责）
```

**节点职责**

| 节点 | 职责 |
|---|---|
| `classify` | 调用 IntentRouter 得到 domain/intent/confidence；路由异常回落内置分类模型 |
| `policy_query` | 查保单（PolicyStore / CoreSystemAdapter），缺保单号反问，降级/失败转人工 |
| `material_gate` | 材料完整性门控 + 提取 claim_id / policy_id / amount |
| `follow_up` | 回流追问，最多 3 轮，超限转人工 |
| `formal_review` | 正式核赔：保单核验 + 三专家并行 + RAG 判责 + 决策路由 |
| `investment_trade` | 交易指令只做安全提示，不调用投资图或下单工具 |

**trace 观测**

`classification` 节点在 SSE trace 中输出：

- `engine`：`jev` / `llm` / `llm-prompt`（回落内置分类时）；
- `route`：`domain` / `intent` / `confidence` / `margin` / `needs_clarification` /
  `fallback_used` / `fallback_reason` / `warnings` / `shadow`；
- `route_error`：路由异常摘要，出现时表示本轮已回落到内置分类模型。

工作台「调用链路 → 平台内核」展示领域意图路由、领域注册校验和影子一致性；
聊天消息上的意图徽章显示引擎，例如 `交易指令 · 100% · JEV`。

**外层执行器**

```text
ainvoke 图 -> 重放 events（trace / intent / material_status / content）
           -> 流式 LLM 回答 -> done
```

注意：

- 一般咨询和理赔问答当前不走知识库 RAG；只有投资意图会调用 `investment_rag`。
- 材料齐全才进入 `formal_review`；缺材料只回流追问。
- 对话链路没有 checkpointer，每次请求新建图；理赔和投资断点续跑在各自接口中完成。
- 交易指令在对话链路只拦截，不执行下单。

## 五、链路② 理赔状态机（`/api/claims/*`）

实现：`agents/claim_agent.py` 的 `build_claim_graph`，带 `AsyncSqliteSaver` 检查点。

```text
START
  -> intake（报案字段核验）
       |-- 缺 policy_id
       |     |-- 已补 < 3 轮 -> interrupt 挂起 -> 等 /supplement -> 回到 intake
       |     |-- 已补 >= 3 轮 -> review 转人工
       |
       |-- 有 policy_id
            -> policy（query_policy 查保单 + verify 核验）
                 |-- 查询/核验失败 -> review 转人工
                 |-- 成功
                      -> experts（子图）
                      -> route_decision（业务规则优先于模型分数）
                            |-- 高风险 risk > 0.7       -> investigate 调查
                            |-- 大额 / 低置信 / 缺证据 -> review 转人工
                            |-- 通过                  -> auto 受理建议（不执行付款）
  -> END
```

**experts 子图**（`build_expert_graph`，作为主图的一个节点）

```text
START
  -> dispatch（Send 扇出，并行）
       |-- expert(damage)     [main/plus]
       |-- expert(risk)       [main/plus]
       |-- expert(liability)  [pro/max]
  -> aggregate（置信度 = min(三专家)，风险分取 risk 专家）
  -> END
```

每个专家都有降级兜底：主档失败回退 `fast/flash`（经 `MiddlewareChain`）。

**决策规则**（`route_decision`）

1. 保单查询失败 / 降级、风险分缺失 -> `review`；
2. `risk_score > 0.7` -> `investigate`；
3. 金额 `> 50000` -> `review`；
4. 保障责任未核实 -> `review`；
5. 命中免责条款且有条款依据 -> `review`；
6. 风险分 `> 0.4`、置信度 `<= 0.9`、专家不足 3 个，或任一专家非 `accept` /
   缺信息 / 降级 -> `review`；
7. 其余 -> `auto`。

**HITL 与写接口**

- 低置信度、缺证据、高风险、大额只允许转人工或调查，不能仅凭分数拒赔。
- 拒赔必须提供核实后的 `clause_basis`；审核必须记录审核员和理由。
- 写接口按 `claim_id` 加进程内锁；同一案号内容不一致返回 409。
- 所有写业务只形成受理/审核建议，不执行付款或通知。

**理赔条款 RAG**

`WorkflowServices` 注入 `clause_retriever` 后，专家先检索适用条款
（`build_clause_retriever` -> `HybridRetriever`，向量 + BM25 加权 RRF），
条款注入 prompt，专家在 `clause_ids` 中引用；引用必须落在已检索条款内。
未配置或检索失败时降级为无条款，不阻断判责。仓库目前主要使用
`tools/demo_clauses.py` 的合成条款，没有内置真实条款语料。

## 六、链路③ 投资域图（`/api/investment/*`）

实现：`agents/investment_agent.py` 的 `build_investment_graph`，与理赔图共用
`.data/checkpoints.sqlite`，通过 `interrupt` 实现二次确认和人工审批。

```text
START
  -> intake
       |-- 交易指令缺 product_id / amount / risk_profile -> interrupt 待补信息
       |-- 交易指令未确认 -> interrupt 二次确认
       |     |-- 用户取消 -> cancelled -> terminal
       |     |-- 用户确认 -> context
       |-- 咨询 / 诊断 / 风险评估 / 产品查询 -> context
  -> context（组合 / 产品 / 行情适配器，失败记录 context_errors，不伪造数据）
  -> risk（风险等级 + 适当性，规则计算，不调用 LLM）
       |-- 交易指令 -> review（人工审批 interrupt）
       |                 |-- approve -> execute
       |                 |-- reject / review -> rejected
       |-- 其他意图 -> advise（形成教育性建议）
  -> execute（submit_trade 适配器）
       |-- 适配器真实执行且回执 executed=true -> decision=execute
       |-- 演示 / 未配置适配器 / 回执未执行 -> decision=review，executed=false
  -> END
```

要点：

- **不接真实券商**：当前 `InvestmentBackend` 未注册真实下单适配器；即使人工审批通过，
  也只有适配器回执明确 `executed=true` 才标记 `executed`。
- **交易指令必须二次确认 + 人工审批**：`/process` 创建请求，`/confirm` 恢复二次确认，
  `/review` 记录审核员和理由；拒绝必须写理由。
- **咨询类请求不触发人工审批**：`advise` 直接形成教育性建议，不构成交易指令。
- **投资图本身不调用 LLM**：风险和适当性由保守规则计算；对话链路的投资问答才使用
  `investment_rag` + investment 模型。
- **适配器失败不伪造结果**：组合/产品/行情不可用时记录 `context_errors`，适当性结论
  标记为待核实。

## 七、RAG 知识库链路

项目有三条独立的检索链路，不要混用集合和权重。

### 7.1 投资 Wiki RAG

- 知识源：`data/investment_wiki/`，7 个 Markdown 文件 + `manifest.json`，当前约 55 个 chunk。
- 入口：`tools/investment_rag.py`。
- 切分：按 Markdown 章节切分，再按长度分段；`doc_id` 由来源、章节、内容和序号生成。
- 召回：`dense=0.55`、`bm25=0.30`、`metadata=0.15`。
- 融合：加权 RRF（`k=60`），再交给 BGE-Reranker 精排。
- 接口：
  - `POST /api/investment/rag/search`：只读检索，返回 `citation_id` / `doc_id` / 标题 / 章节 / 来源；
  - `/api/assistant/stream` 的投资意图：检索结果注入投资问答 Prompt，回答使用 `[K1]` 形式的引用。
- 向量不可用时自动降级为 `bm25 + metadata`，`vector_ready=false`，原因写入 `vector_error`。

### 7.2 通用知识库 RAG

- 知识源：`data/knowledge_base/`，支持 `.md/.markdown/.txt/.pdf/.docx/.html/.htm`。
- 入口：`tools/knowledge_rag.py`。
- domain：`general`（`data/knowledge_base`）和 `investment`（投资 Wiki）；
  两个 domain 共用 `KnowledgeRAG`，按需懒加载。
- 切分：Markdown 按 `##` 章节；文件标题、免责声明合并到第一个章节；
  `参考资料 / 参考来源 / 参考文献 / 延伸阅读 / 相关链接` 不进入索引。
- 召回与融合：与投资 Wiki 相同的三路召回、加权 RRF 和 BGE-Reranker。
- 接口：
  - `GET /api/rag/domains`：列出 domain、集合、是否已加载、语料数量；
  - `POST /api/rag/search`：返回 Top-K 片段、引用和检索诊断；
  - `POST /api/rag/answer`：检索后调用 LLM 生成 JSON 回答，并校验 `citation_ids`
    必须来自本轮检索结果；无有效引用时转人工。
- 当前 `data/knowledge_base/` 只有少量示例文档，主要用于验证链路，不代表完整业务知识库。

### 7.3 理赔条款 RAG

- 入口：`tools/rag_retrieval.py`。
- 集合：每个险种一个集合 `claims_<insurance_type>`。
- 召回：向量 + BM25 两路，默认权重 `0.7/0.3`，加权 RRF（`k=60`）。
- 过滤：按 `insurance_type` / `version` 过滤；`drop_old=False`，不自动清空旧条款。
- 引用：专家输出的 `clause_ids` 必须来自本轮检索结果；未配置检索器或失败时降级为无条款。
- 仓库没有内置真实条款语料，演示使用 `tools/demo_clauses.py` 的合成条款。

### 7.4 降级与诊断

- 向量服务或 Milvus 不可用：自动降级为 BM25 + metadata，`vector_ready=false`，
  原因写入 `route_errors` / `vector_error`。
- BGE-Reranker 不可用：降级为词项重排，`rerank_fallback=true`，失败后默认冷却 60 秒。
- 每次检索同时：
  - 写入结构化 `rag.retrieval` 日志；
  - 追加到审计 `details.retrieval`；
  - 通过 API 返回 `retrieval` 诊断。
- 关键诊断字段：`route_hits`、`route_errors`、`fused_count`、`rerank_candidates`、
  `rerank_top_n`、`reranked`、`rerank_fallback`、`rerank_error`、`returned`。

## 八、其他 LangGraph / LangChain 结构

以下结构在 `agents/claim_agent.py` 中提供，但**未接入主 app**：

| 结构 | 说明 |
|---|---|
| `build_plan_execute` | Plan-and-Execute 图：planner -> execute 循环（≤8 步） |
| `create_model_plan_execute` | pro(max) 规划 + main(plus) 执行，只分析不执行 |
| `create_basic_agent` | `AgentExecutor` + `create_tool_calling_agent`（工具调用闭环） |
| `create_conversational_agent` | `RunnableWithMessageHistory`，按 session_id 隔离历史 |

八类业务工具经 `tools/claim_tool.py` 的 `build_claim_tools` 注册；
`isolated_deep/runtime.py`（deep agents 隔离环境）单独使用该工具集，主 app 未接入。

## 九、大模型判断位置汇总

模型档位：`fast/flash`、`main/plus`、`pro/max`、`vision`；
业务任务通过 `TASK_PROFILES` 选择档位，未知任务显式报错，不自动降级判责。

| 环节 | 模型档位 | 说明 |
|---|---|---|
| 意图分类（入口路由） | JEV `ateve-jev-v1` / flash | 输出 domain + intent + confidence；代码默认 shadow，当前 `.env` 为 hybrid |
| 意图翻译（可选） | flash | `INTENT_TRANSLATE_TO_ENGLISH=true` 时先翻译再送 JEV；当前 DeepSeek 下不可用，见边界 |
| 单证识别 | extraction/plus + vision | 识别上传的发票 / 病历 / 事故单 |
| 损失 / 风险专家 | main/plus | 降级回退 fast/flash |
| 责任专家 | pro/max | 降级回退 fast/flash |
| 理赔 / 客服回答 | plus | `customer_service` 档 |
| 对话投资问答 | plus | 投资 RAG 检索后生成回答 |
| 通用知识库回答 | plus | `/api/rag/answer` 使用 main/plus |
| 投资域图 | 不调用 LLM | 风险等级和适当性由规则计算 |
| 进度查询 / 轻量任务 | flash | `status_query` 等 |

## 十、意图路由（JEV / LLM / Hybrid / Shadow）

接入位置：`agents/assistant_agent.py` 的 `classify` 节点；适配层是
`agent_core/intent/adapter.py` 的 `AssistantIntentRouter`，它把工作台请求转成
`IntentRequest`，再把 `RouteDecision` 收敛成 `IntentResult`。

```text
INTENT_ROUTER_ENABLED=true
  -> IntentConfig.from_settings(Settings)
  -> build_intent_classifier()          # agent_core/intent/factory.py
       primary / fallback / shadow
  -> AssistantIntentRouter
  -> graph classify 节点
  -> 路由异常时回落内置分类模型，SSE 不中断
```

| `INTENT_ENGINE` | primary | fallback | shadow | 适用 |
|---|---|---|---|---|
| `shadow`（代码默认） | LLM | 无 | JEV | 生产稳定 + 影子对拍 |
| `hybrid`（当前 `.env`） | JEV | LLM | 无 | JEV 主路由，低置信/异常时 LLM 兜底 |
| `jev` | JEV | 无 | 无 | 单引擎验证 |
| `llm` | LLM | 无 | 无 | 与旧链路等价 |

约定：

- 阈值：`confidence >= INTENT_CONFIDENCE_THRESHOLD(0.8)`、
  `margin >= INTENT_MARGIN_THRESHOLD(0.2)`；低于阈值触发兜底或标记
  `needs_clarification`。
- 领域和意图注册表：`configs/domains.yaml` + `agent_core/intent/registry.py`。
  新增意图必须补 `description_en`，JEV 使用英文描述。
- JEV 是英文优先模型；中文输入可开 `INTENT_TRANSLATE_TO_ENGLISH=true`，
  未开翻译会记录 `cjk_without_translation` 警告。
- 发送前先 `mask_pii`，JEV 只收到脱敏文本；`JEV_API_KEY` 只从环境变量 / `.env`
  读取，不写入日志、报告和镜像。
- JEV 对 `429` / 全部 `5xx`（含网关 `529 model busy`）做有界重试：
  `JEV_MAX_RETRIES` 默认 2（最多 5），`JEV_RETRY_BACKOFF_S` 默认 0.25，
  指数退避；请求是只读分类，重试无副作用。
- 缺 `JEV_API_KEY` 时影子自动跳过；若设成 `jev/hybrid` 主路由而缺 key，
  `build_assistant_intent_router()` 返回 `None`，主链路回落内置分类，服务照常启动。
- 保单号：JEV 不返回槽位，`AssistantIntentRouter` 对「保单查询」意图用本地正则从
  当前问题和历史中补齐；识别不到仍反问保单号。
- 关闭开关：`INTENT_ROUTER_ENABLED=false`。

**日志**

- `intent.route`：兜底后的最终决策，由 `app.py` 记录，字段包括 `engine`、`domain`、
  `intent`、`confidence`、`margin`、`fallback`、`reason`、`clarification`、`shadow`、`warnings`。
- `intent.primary_low_confidence`：主路由低置信，记录主引擎结果和兜底引擎。
- `intent.primary_failed`：主路由异常，记录异常类型和兜底引擎。
- `intent.jev_retry`：JEV 429/5xx 重试，记录尝试次数、状态码和退避时间。
- 这些日志只记录意图元数据，不记录用户原文。

**评测**

```bash
.venv-py315/bin/python -m scripts.eval_intent --engine jev --data data/intent_golden.jsonl
.venv-py315/bin/python -m scripts.eval_intent --engine shadow --limit 20
.venv-py315/bin/python -m scripts.eval_intent --engine hybrid --min-accuracy 0.9
```

2026-10-27 实测（JEV 单引擎，39 条合成样本）：联合准确率 `0.897`、领域 `1.000`、
意图 `0.897`、P50/P95 `571/628ms`；主要错误为「组合诊断 ↔ 投资咨询」。

## 十一、运行期数据与持久化

```text
.data/checkpoints.sqlite  <- 理赔 / 投资图断点与恢复（AsyncSqliteSaver）
.data/audit.sqlite        <- 接入层请求审计（只追加 + 哈希链，可 verify_chain）
.data/policies.sqlite     <- 本地模拟保单（PolicyStore，demo）
.data/outbox.sqlite       <- 赔付 / 通知回写队列（Outbox 已实现，主图未注入，入队 ≠ 付款）
.data/milvus.db           <- 本地 Milvus Lite 向量库
.data/logs/app.log        <- 应用日志，含 rag.retrieval / intent.route
.data/logs/uvicorn.log    <- uvicorn 启动 / 访问 / 异常日志
```

- `.data/` 全部 gitignore，不要提交。
- 本地 Milvus Lite 只适合单进程；多副本前换 Postgres/Redis + 远程 Milvus。
- 远程 / 容器向量库使用 `MILVUS_URI=http://127.0.0.1:19530`；
  本地 Lite 使用 `VECTOR_STORE_URI=./.data/milvus.db`。
- 审计哈希链可用 `scripts/audit_verify.py` 校验。
- 单机 SQLite + Milvus Lite 只适合单进程；多副本前换基础设施。

## 十二、当前边界

- **JEV 已接管主路由（hybrid）**：当前 `.env` 为 `INTENT_ENGINE=hybrid`；
  39 条评测联合准确率 `0.897`，主要残余混淆是「组合诊断 ↔ 投资咨询」。
- **JEV 中文边界仍不稳**：官方定位英文优先；扩充语料前不要切 `jev` 单引擎。
- **翻译开关当前不可用**：`LLMTranslator` 复用 `classification` 模型（`json_object`），
  DeepSeek 会因 prompt 不含 “json” 返回 400；开启
  `INTENT_TRANSLATE_TO_ENGLISH=true` 前需先改为 text 模式模型，并重新跑评测。
- **真实理赔闭环未完成**：`BusinessBackend` 只内置 `query_policy`，
  `verify_claim_evidence` 需注册适配器；`CORE_QUERY_URL` 为空时安全降级为转人工。
- **真实条款语料缺失**：支持 `claims_<险种>` 集合，但仓库没有真实条款，
  主要用演示条款。
- **真实下单未接入**：投资域图只有适配器接口和演示回执，不会真实下单。
- **交易缺字段恢复不完整**：交易指令缺 `product_id` / `amount` / `risk_profile` 时，
  图会 `interrupt` 返回待补字段，但 HTTP 层没有独立的“补字段恢复”接口；
  调用方应在首次请求中提供完整字段，否则当前需要重新发起。
- **RAG 评测缺失**：有意图评测，但没有覆盖投资 / 通用 / 理赔的 golden QA、
  Recall@K / MRR / nDCG / 引用准确率回归。
- **一般问答不走知识库 RAG**：对话链路只有投资意图调用 `investment_rag`；
  通用问答和理赔问答当前不使用 `knowledge_rag`。
- **Reranker 懒加载**：`/health` 在 reranker 未加载时仍可能返回 ok，
  首次检索会多几秒。
- **单机限制**：SQLite + Milvus Lite 只适合单进程；多副本需换基础设施。
- **线上安全**：仍是 development + nginx Basic Auth，需换默认口令、补 nginx 限流、
  SSH 密钥、日志轮转、`.data` 备份和外部监控。
- **CI/CD 未统一**：`.github/workflows/deploy.yml` 与 `scripts/deploy_vps.sh`
  的 rsync 流程不一致，需要二选一。
