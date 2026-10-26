# 理赔 Agent 架构

## 一、全景分层架构

```
【前端层】
  理赔工作台 UI（聊天 / 单证上传 / 链路可视化）
       |
       v   HTTP / SSE
【接入层】 EnterpriseHttpMiddleware（纯 ASGI，每个请求）
  CORS -> RequestID -> 认证 -> 体积上限 -> 限流 -> 审计 -> 500 兜底
  认证：/api/* 校验 X-API-Key；生产启动强制配置密钥
  限流：身份 + IP + 接口类别（进程内；多副本需 Redis）
  审计：脱敏入参 + RAG 检索诊断写入 audit.sqlite，只追加 + 哈希链
       |
       v
【路由层】 app.py (FastAPI) —— 纯 URL 静态匹配，无大模型
  /api/assistant/stream                     -> 链路① 对话助手
  /api/claims/process · supplement · review · {id}  -> 链路② 理赔状态机
  /api/documents/analyze                    -> 单证识别
  /api/demo/claims/process                  -> 演示（复用链路②）
  /health · /ready · /metrics               -> 存活 / 就绪 / 指标
       |
       v
【编排层】
  链路① 对话助手(LangGraph)  : classify(IntentRouter: JEV/LLM/Hybrid) -> investment / policy_query / material_gate -> follow_up（回答外层流式）
  链路② 理赔状态机(LangGraph) : intake -> policy -> experts(子图) -> auto/review/investigate
       └ experts 子图          : expert(Send 扇出三专家) -> aggregate
  链路③ 工具/规划(未接主app)  : AgentExecutor、Plan-and-Execute、RunnableWithMessageHistory
       |
       v
【服务层】
  WorkflowServices（policy / verify / expert + clause_retriever 条款检索）
  MiddlewareChain（三专家：脱敏 -> 按案限流 -> 缓存 -> 推理 -> 降级 -> 审计 -> HITL 标记）
       |
       v
【适配器层】
  BusinessBackend -> CoreSystemAdapter（HTTP + 熔断 + 只读缓存）-> 核心系统
  DemoBackend     -> PolicyStore（SQLite: policies.sqlite）
       |
       v
【模型层】
  flash（分类/轻量/降级）· plus（通用/客服/主专家）· max（责任专家/强推理）· vision（单证视觉）
  JEV（远程意图分类，可选；ateve-jev-v1，英文优先）
       |
       v
【数据层】
  SQLite : checkpoints.sqlite（状态机检查点）
           audit.sqlite     （请求审计，只追加 + 哈希链）
           policies.sqlite  （本地保单，新增）
           outbox.sqlite    （回写队列；组件已实现，主图未注入）
  Redis（会话历史，可选）· Milvus（条款向量，可选）· 核心系统 HTTP（真实保单）

【横切】 接入层：RequestID / 认证 / 限流 / 审计；意图路由：JEV / LLM / Hybrid / Shadow；
        模型层：脱敏 / 缓存 / 降级；观测：LangFuse / Prometheus / stdout JSON
```

## 一·补充、生产部署形态（单机）

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
- `/ai/` 反向代理时去掉前缀：`/ai/api/... -> /api/...`、`/ai/static/... -> /static/...`。前端资源与 API 使用相对路径，因此本地 `/` 和线上 `/ai/` 共用一份代码。
- BGE-M3 与 BGE-Reranker 放在独立 `embed` 容器，模型以只读 bind mount 挂载；应用和模型服务共享 Compose 网络。
- `.data/` 使用 bind mount 持久化 Milvus Lite、审计库、检查点和日志。不要多进程写同一个 Milvus Lite 文件。
- 当前前端不发送 `X-API-Key`，公网入口使用 `APP_ENV=development` + nginx Basic Auth；若要切到 `APP_ENV=production`，必须同时解决前端密钥注入。

## 二、入口路由：三层，只有意图层做模型判断

```
HTTP 路由（无模型，静态 URL 匹配）
  /api/assistant/stream  /api/claims/*  /api/documents/analyze ...
        │
        ├─ /api/assistant/stream ──▶ IntentRouter（JEV / LLM / Hybrid / Shadow）
        └─ /api/claims/* ─────────▶ 直接进入理赔状态机（无意图路由）
```

1. **HTTP 层路由**（FastAPI 装饰器）—— 纯 URL 匹配，请求打到哪个 endpoint 是写死的，**没有大模型**。
2. **意图路由层** —— 进入 `/api/assistant/stream` 后，`IntentRouter` 判定 `domain + intent + confidence`：
   - `shadow`（默认）：LLM 主路由，JEV 影子并行只记录；
   - `hybrid`：JEV 主路由，低置信或异常时 LLM 兜底；
   - `jev` / `llm`：单引擎。
3. **图内业务分流** —— 依据 `intent` 进入投资、保单查询、材料门控等节点。

```
用户消息 + 附件 + 历史
  -> 意图路由（IntentRouter）   <-- 唯一的意图判断入口
       JEV: ateve-jev-v1（远程） / LLM: flash 档
       输出: RouteDecision(domain, intent, confidence, margin, warnings, shadow)
  -> 适配为工作台 IntentResult(intent, confidence, policy_id)
  -> 按 intent 分流
       |-- 一般咨询     -> general 模型
       |-- 投资意图     -> investment_rag -> investment 模型
       |-- 交易指令     -> 拦截，不执行下单
       |-- 保单查询     -> 查后端（PolicyStore / CoreSystemAdapter）
       |-- 其他理赔意图 -> customer_service 模型（材料门控在前）
```

对应代码：

```python
# app.py：启动时按配置构建一次，失败降级为内置分类
router = build_assistant_intent_router(cfg, intent_model)      # agent_core/intent/factory.py
# agents/assistant_agent.py：classify 节点优先走路由层
route = await intent_router.classify(question=..., history=..., active_domain=...)
intent = IntentResult(intent=route.intent, confidence=route.confidence, policy_id=route.policy_id)
# 路由异常时回落内置分类模型，SSE 不中断，trace 记录 route_error
```

`INTENT_ROUTER_ENABLED=false` 可整体关闭路由层，回到内置 LLM 分类；路由引擎与阈值见
`INTENT_ENGINE` / `INTENT_*` / `JEV_*`。

## 三、链路① 对话助手（LangGraph 多节点，/api/assistant/stream）

方案 A：无状态多节点图（`agents/assistant_agent.py`）。图负责编排决策，LLM 流式回答由外层执行器负责。

```
START
  -> classify（IntentRouter：JEV/LLM/Hybrid，默认 shadow；输出 intent + confidence + policy_id）
  -> 条件路由 route_after_classify
       |-- 一般咨询  -> END（外层流式 general 回答）
       |-- 投资意图  -> 投资 RAG -> END（外层流式 investment 回答）
       |-- 交易指令  -> investment_trade -> END（只拦截，不下单）
       |-- 保单查询  -> policy_query -> END（反问保单号 / 输出保单摘要）
       |-- 其他理赔  -> material_gate
                          |-- 缺材料 -> follow_up -> END（回流追问，最多 3 轮 -> 转人工）
                          |-- 材料齐 -> formal_review -> END（三专家 + RAG 判责）
```

**节点职责**

| 节点 | 职责 |
|---|---|
| classify | 调用 IntentRouter 得到 domain/intent/confidence，路由失败回落内置分类模型 |
| policy_query | 查保单（PolicyStore / CoreSystemAdapter），缺保单号反问，降级/失败转人工 |
| material_gate | 材料完整性门控 + 提取结构化字段（claim_id / policy_id / amount） |
| follow_up | 回流追问，最多 3 轮，超限转人工 |
| formal_review | 正式核赔：保单核验 + 三专家并行 + RAG 判责 + 决策路由 |

**trace 观测**

`classification` 节点在 SSE trace 中额外输出：

- `engine`：`jev` / `llm` / `llm-prompt`（回落内置分类时）；
- `route`：`domain` / `intent` / `confidence` / `margin` / `needs_clarification` /
  `fallback_used` / `warnings` / `shadow`；
- `route_error`：路由异常摘要，出现时表示本轮已回落到内置分类。

工作台展示位置：「调用链路 → 平台内核」下

- **领域意图路由**：显示 `JEV 意图模型 / LLM 意图路由 / 内置分类模型`、是否兜底、
  影子一致性，展开「输入 / 输出参数」可见 `engine`、`domain`、`intent`、`confidence`、
  `fallback_reason`、`warnings`、`shadow`；
- **领域注册校验**：显示 `已校验 <domain> / <intent>`；
- 聊天消息上的意图徽章同时显示引擎，例如 `交易指令 · 100% · JEV`。

**外层执行器**（`app.py` 的 `assistant_stream`）

```
ainvoke 图 -> 重放 events（trace + intent + material_status + content）-> 流式 LLM 回答 -> done
```

> 链路① 的对话预审与正式核赔已分开：材料齐全才进入 `formal_review`（三专家 + RAG 判责），
> 缺材料只回流追问；交易指令只拦截不下单。
> 当前为方案 A（无状态，每次请求新建图）；方案 B（checkpointer + interrupt 断点续跑）见 README。

## 四、链路② 理赔状态机（LangGraph，/api/claims/*）

主图（`agents/claim_agent.py` 的 `build_claim_graph`），带 checkpointer：

```
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
                      -> experts（子图，见下）
                      -> route_decision（业务规则优先于模型分数）
                            |-- 高风险(risk>.7)       -> investigate 调查
                            |-- 大额 / 低置信 / 缺证据 -> review 转人工（interrupt 挂起等 /review）
                            |-- 通过                  -> auto 受理建议（不执行付款）
  -> END
```

**experts 子图**（`build_expert_graph`，作为主图的一个节点）

```
START
  -> dispatch（Send 扇出，并行）
       |-- expert(damage)     [plus/main]
       |-- expert(risk)       [plus/main]
       |-- expert(liability)  [max/pro]
  -> aggregate（置信度 = min(三专家)，风险分取 risk 专家）
  -> END
```

> 每个专家有降级兜底：主档失败回退 `flash/fast`（经 `MiddlewareChain` 的 fallback）。
> 判责条款检索（RAG）：`WorkflowServices` 注入 `clause_retriever` 后，专家先检索适用条款
> （`build_clause_retriever` -> `HybridRetriever`，向量 + BM25 加权 RRF），条款注入 prompt，
> 专家在 `clause_ids` 中引用；引用必须落在已检索条款内，未配置或检索失败降级为无条款。
>
> 通用知识库 RAG：`tools/knowledge_rag.py` 对 `data/knowledge_base/` 和投资 Wiki 做
> dense + BM25 + 元数据三路召回，加权 RRF 后用 BGE-Reranker 精排；`/api/rag/search`
> 返回片段与引用，`/api/rag/answer` 生成答案并校验 `citation_ids`。
> 当前 `models/bge-reranker-base` 已下载并启用，正常检索返回
> `rerank_fallback=false`；模型或服务不可用时自动降级为词项重排。

## 五、其他 LangGraph/LangChain 结构（`claim_agent.py`，未接主 app）

| 结构 | 说明 |
|---|---|
| `build_plan_execute` | Plan-and-Execute 图：planner -> execute 循环（≤8 步） |
| `create_model_plan_execute` | pro(max) 规划 + main(plus) 执行，只分析不执行 |
| `create_basic_agent` | `AgentExecutor` + `create_tool_calling_agent`（工具调用闭环） |
| `create_conversational_agent` | `RunnableWithMessageHistory`，按 session_id 隔离历史 |

> 八类业务工具经 `tools/claim_tool.py` 的 `build_claim_tools` 注册；`isolated_deep/runtime.py`（deep agents 隔离环境）单独使用该工具集，主 app 未接入。

## 六、大模型判断位置汇总

| 环节 | 模型档位 | 说明 |
|---|---|---|
| 意图分类（入口路由） | JEV `ateve-jev-v1` / flash | 输出 domain + intent + confidence；默认 shadow 由 LLM 主路由 |
| 单证识别 | vision / plus | 识别上传的发票/病历/事故单 |
| 损失/风险专家 | plus（main） | 降级回退 flash |
| 责任专家 | max（pro） | 降级回退 flash |
| 回答生成 | plus | 客服/通用回答 |
| 意图翻译（可选） | flash | `INTENT_TRANSLATE_TO_ENGLISH=true` 时把中文转英文再送 JEV |

## 六·补充、意图路由（JEV / LLM / Hybrid / Shadow）

接入位置：`agents/assistant_agent.py` 的 `classify` 节点。
适配层：`agent_core/intent/adapter.py`（`AssistantIntentRouter`）把工作台请求转成
`IntentRequest`，再把 `RouteDecision` 转成 `IntentResult`。

```text
INTENT_ROUTER_ENABLED=true
  -> IntentConfig.from_settings(Settings)
  -> build_intent_classifier()  # agent_core/intent/factory.py
       primary / fallback / shadow
  -> AssistantIntentRouter
  -> graph classify 节点
```

| `INTENT_ENGINE` | primary | fallback | shadow | 适用 |
|---|---|---|---|---|
| `shadow`（代码默认） | LLM | 无 | JEV | 生产稳定 + 影子对拍 |
| `hybrid`（当前 `.env`） | JEV | LLM | 无 | 中文评测达标后接管 |
| `jev` | JEV | 无 | 无 | 单引擎验证 |
| `llm` | LLM | 无 | 无 | 与旧链路等价 |

约定：

- 阈值：`confidence >= INTENT_CONFIDENCE_THRESHOLD(0.8)`、
  `margin >= INTENT_MARGIN_THRESHOLD(0.2)`；低于阈值触发兜底或标记 `needs_clarification`。
- JEV 是英文优先模型；中文输入可开 `INTENT_TRANSLATE_TO_ENGLISH=true`，
  未开翻译会记录 `cjk_without_translation` 警告。
- 发送前先 `mask_pii`，JEV 只收到脱敏文本；`JEV_API_KEY` 不写入日志、报告和镜像。
- 缺 `JEV_API_KEY` 时影子自动跳过；若设成 `jev/hybrid` 主路由而缺 key，
  `build_assistant_intent_router()` 返回 `None`，主链路回落内置分类，服务照常启动。
- 保单号：JEV 不返回槽位，`AssistantIntentRouter` 对「保单查询」意图用本地正则从
  当前问题与用户历史中补齐；识别不到仍按原逻辑反问保单号。
- 关闭开关：`INTENT_ROUTER_ENABLED=false`。
- 观测：`intent.route` 日志（不含用户原文）+ SSE trace 的 `engine` / `route` / `route_error`。
- 评测：`scripts/eval_intent.py` + `data/intent_golden.jsonl`。
- 2026-10-27 实测（JEV 单引擎，39 条）：联合准确率 `0.897`、领域 `1.000`、意图 `0.897`、
  P50/P95 `571/628ms`；主要错误为「组合诊断 ↔ 投资咨询」。

## 七、四处 SQLite 职责

```
checkpoints.sqlite  <- 链路② 状态机断点/恢复（AsyncSqliteSaver）
audit.sqlite        <- 接入层 请求审计（只追加 + 哈希链，可 verify_chain）
policies.sqlite     <- 链路① 保单查询的本地模拟数据（PolicyStore）
outbox.sqlite       <- 赔付/通知回写队列（Outbox 已实现，主图未注入，入队 ≠ 付款）
```
