#  AI Agent 平台：架构与工作流

> 版本：v0.1  
> 适用范围：当前仓库的理赔对话、理赔案件，以及规划中的投资 / 通用领域。  
> 标记说明：`[现有]` 表示当前代码已有；`[新增]` 表示本次已落地；`[规划]` 表示设计已定，尚未接入。

---

## 0. 先看结论

这套系统可以类比成一家医院：

| 医院 | 系统 |
|---|---|
| 前台 | FastAPI 接入层 |
| 分诊台 | `IntentRouter` 意图路由 |
| 科室 | `DomainPlugin`：claims / investment / general |
| 医生问诊、检查 | LangGraph 图执行 |
| 化验、影像、会诊 | RAG、三专家并行、工具调用 |
| 主任复核 | HITL 人工审核 |
| 挂号、病历、支付系统 | Capability SPI |

一句话：

```text
分诊台只负责“去哪个科室”，不负责“怎么治病”；
科室才是业务，底层系统负责可扩展。
```

---

## 1. 分层架构图

```text
┌────────────────────────────────────────────────────────────────────┐
│ 用户 / Web / App                                                   │
│  发消息、上传材料、查进度、发起交易                                 │
└───────────────────────────────┬────────────────────────────────────┘
                                │ HTTPS / SSE
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 1. 接入层 [现有]                                                   │
│    FastAPI app.py                                                  │
│    ├─ /api/assistant/stream   对话流式入口                         │
│    ├─ /api/claims/*           理赔案件接口                         │
│    └─ SSE / JSON                                                  │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 2. 中间件链 [现有]                                                 │
│    Auth → RateLimit → PII Mask → Cache → Audit → HITL Gate         │
└───────────────────────────────┬────────────────────────────────────┘
                                │ IntentRequest
                                │ message / history / active_domain / attachments
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 3. 意图路由 [新增]                                                 │
│    IntentRouter / HybridIntentClassifier                           │
│    ├─ shadow（默认）：LLM 主路由 + JEV 影子                        │
│    ├─ hybrid：JEV 主路由 + LLM 兜底                                │
│    └─ 输出 RouteDecision                                           │
│         domain / intent / confidence / margin / 是否澄清           │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 4. 领域注册 [新增]                                                 │
│    DomainRegistry ← configs/domains.yaml                           │
│    校验：domain、intent 必须存在                                   │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 5. 领域插件 [部分现有 / 部分规划]                                  │
│                                                                    │
│  ClaimsPlugin          InvestmentPlugin        GeneralPlugin       │
│  ├─ 理赔对话图          ├─ 组合诊断图           └─ 一般问答图       │
│  ├─ 理赔案件状态机      ├─ 风险评估图                               │
│  ├─ 三专家并行          ├─ 产品查询图                               │
│  └─ RAG + HITL          └─ 交易指令图 + HITL                        │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 6. 图执行 [现有]                                                   │
│    LangGraph：节点编排 / 条件边 / 并行 / 工具 / RAG                 │
│    Checkpointer：保存会话与案件状态                                 │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 7. 能力层 Capability SPI [接口新增，外部实现规划]                  │
│    StateStore / TaskQueue / Lock / RateLimiter / EventBus / Outbox  │
│    ObjectStore / VectorStore / Audit / HITL / ModelGateway          │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ 8. 输出与观测                                                      │
│    SSE/JSON 回复 → 用户                                            │
│    Outbox 事件 → Kafka/DB/重试 [规划]                              │
│    Langfuse / Metrics / 审计日志 [现有/规划]                       │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. 端到端工作流

```text
用户
 │
 │ 1. 发消息 / 上传材料
 ▼
┌──────────────────────────────────────────────────────────────┐
│ 2. FastAPI 接入层                                             │
│    /api/assistant/stream   /api/claims/*                     │
│    SSE 流式返回                                              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 3. 中间件链                                                   │
│    Auth → RateLimit → PII Mask → Cache → Audit → HITL Gate   │
└──────────────────────────┬───────────────────────────────────┘
                           │ IntentRequest
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 4. 意图路由 IntentRouter                                      │
│    shadow: LLM 主 + JEV 影子                                  │
│    hybrid: JEV 主 + LLM 兜底                                  │
│    输出: domain / intent / confidence / margin               │
└──────────────────────────┬───────────────────────────────────┘
                           │ RouteDecision
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 5. 领域注册 DomainRegistry                                    │
│    校验 domain + intent 是否在 configs/domains.yaml           │
└──────────────────────────┬───────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
     ClaimsPlugin    InvestmentPlugin   GeneralPlugin
          │                │                │
          ▼                ▼                ▼
   理赔对话/案件图    投资组合/风险图     一般问答图
          │                │                │
          └────────────────┼────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 6. 图执行 LangGraph                                           │
│    节点编排 / 条件路由 / 并行专家 / RAG / 工具调用             │
│    Checkpointer 保存状态                                      │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ 7. Capability SPI                                             │
│    StateStore / Queue / Lock / RateLimit / EventBus / Outbox  │
│    ObjectStore / VectorStore / Audit / HITL / ModelGateway    │
└──────────────────────────┬───────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      SSE 流式回复      事件写入 Outbox    指标/审计
          │                │                │
          ▼                ▼                ▼
        用户           Kafka/DB/重试      Langfuse/Metrics
```

### 2.1 关键分叉：不是所有请求都进案件状态机

```text
                        ┌─ 低风险、问答型 ──▶ 对话链路（SSE，快速返回）
RouteDecision ──判断──┤
                        └─ 高风险、长事务 ──▶ 案件链路（状态机，HITL）
```

例如：

```text
“理赔到哪一步了？”          → 对话链路，查状态后直接回复
“我的车被追尾了，怎么报案？”  → 对话链路，引导报案 / 补材料
“提交这个理赔案件”            → 案件链路，进入状态机
“帮我把基金赎回”              → 高风险，案件模式 + 人工审批
```

### 2.2 一次请求的十步

```text
1. 用户发消息，或上传材料
2. FastAPI 接收，建立 SSE 流
3. 中间件做鉴权、限流、PII 脱敏、缓存、审计
4. 组装 IntentRequest：
      message / history / active_domain / attachments
5. IntentRouter 判断：
      domain     = claims / investment / general
      intent     = 领域内具体意图
      confidence / margin
6. DomainRegistry 校验 domain + intent 是否合法
7. 选择 DomainPlugin：
      低风险 → 对话图
      高风险 → 案件图
8. LangGraph 执行节点：
      分类 / 材料门禁 / 查询 / RAG / 三专家并行
9. 高风险节点触发 HITL：
      人工审核 / 二次确认 / 补件
10. 结果通过 SSE 返回
11. 审计、事件、指标写入 Outbox / Langfuse / 日志
```

### 2.3 中间件链：实现映射（v0.2）

上面架构图里的 `Auth → RateLimit → PII Mask → Cache → Audit → HITL Gate`，现在拆成**两层**落地：

```text
【接入层】EnterpriseHttpMiddleware（每个 HTTP 请求，新增路由自动继承）
   RequestID → 认证 → 体积限制 → 限流 → 审计开始 → 业务 → 审计结束/异常兜底
   代码：agents/http_middleware.py

【模型调用层】MiddlewareChain（只包住三专家的 LLM 调用）
   脱敏 → 按案限流 → 缓存 → 熔断/重试/降级 → 输出护栏 → HITL 标记 → 审计
   代码：agents/middleware_audit.py
```

| 能力 | 接入层（全局） | 模型层（专家调用） |
| --- | --- | --- |
| 认证 | 接入层强制 `X-API-Key`；`X-Reviewer-Key` 由审核类接口校验；`/api/demo/*` 与探针公开 | — |
| 限流 | 按「身份 + 来源 IP + 接口类别」分桶：通用 1200/min、流式 120/min、单证 120/min | 每案件 10 令牌、1/s |
| 脱敏 | 审计落库前统一 `mask_pii`，日志只存 IP 哈希 | 输入/输出/缓存值全部脱敏 |
| 审计 | append-only + 哈希链（`agents/audit_store.py`），记录 request_id/状态/耗时/脱敏入参 | stdout JSON 明细 |
| 缓存 | —（暂不做 HTTP 级缓存） | 进程内 TTL，key = 案件 + 输入 + 模型参数 |
| HITL | — | 打 `requires_manual_review` 标记 |
| 真正 HITL 闸门 | LangGraph `interrupt()` + `/api/claims/{id}/review` + 审核员密钥 | — |
| 异常兜底 | 未处理异常返回 500 + request_id，不泄露堆栈 | 3 次重试后切 `fast` 模型并标记 `degraded` |

审计验证：

```bash
python -m scripts.audit_verify --limit 10    # 退出码 0 = 链完整
```

尚未覆盖（后续版本）：Redis 分布式限流、Postgres 审计、语义缓存、多租户、策略中心（OPA）。
接入层限流与审计缓存都在单进程内，多副本部署前必须外置。

---

## 3. 理赔对话链路（当前实际）

```text
用户消息
  │
  ▼
/api/assistant/stream
  │
  ▼
build_assistant_graph
  │
  ▼
classify（识别理赔意图）
  │
  ├─ 理赔报案 / 材料审核 / 补充材料
  │       │
  │       ▼
  │   material_gate
  │       ├─ 材料齐全 ──▶ 业务处理 / RAG / 工具
  │       └─ 材料缺失 ──▶ 生成补件清单
  │
  ├─ 进度查询 / 保单查询 / 条款咨询
  │       └─▶ 查询工具 / 条款 RAG
  │
  ▼
formal_review（正式性 / 合规复核）
  │
  ▼
SSE 流式返回
```

这条链路的特点是：

- **轻量、同步 / 流式、低风险**
- 主要解决“问、查、引导、补件提示”
- 当前 `app.py` 仍然走这条链路里的 `classify` 节点
- 目标态下，`classify` 会由新的 `IntentRouter` 接管或前置

---

## 4. 理赔案件链路（当前实际）

```text
创建 / 提交案件
  │
  ▼
材料接收 → OCR / 解析 → 完整性检查
  │
  ├─ 材料不全 ──▶ 通知补件 ──▶ 等待上传 ──┐
  │                                        │
  ▼                                        │
三专家并行（医疗 / 责任 / 损失）           │
  │        │        │                      │
  └────────┼────────┘                      │
           ▼                               │
      结果聚合 / 交叉校验 ◀────────────────┘
           │
           ▼
      route_decision
           │
     ┌─────┴─────┐
     ▼           ▼
  自动通过     转人工复核（HITL）
     │           │
     │           ▼
     │      审核员：批准 / 拒绝 / 补件
     │           │
     └─────┬─────┘
           ▼
      结案 / 赔付 / 拒赔
           │
           ▼
      审计 + 通知 + Outbox 事件
```

这条链路的特点是：

- **重、长事务、状态机**
- 三专家并行，结果聚合后再做路由决策
- `route_decision` 决定自动通过还是转人工
- HITL 是高风险场景的硬门禁
- 意图识别不会替代案件状态机，只负责把用户引导到正确入口

---

## 5. 投资链路（规划）

```text
用户：基金组合怎么配置 / 帮我赎回
  │
  ▼
IntentRouter → investment
  │
  ├─ 投资咨询 / 组合诊断 / 风险评估 / 产品查询
  │      → PortfolioGraph / RiskGraph / ProductGraph
  │      → 行情、产品数据、RAG
  │      → 诊断报告 + 风险提示
  │
  └─ 交易指令（high risk / case mode）
         → 适当性校验
         → 二次确认
         → HITL 人工审批
         → 交易适配器（券商 / 基金平台）
         → 回执 + 审计
```

投资域和理赔域共用同一套内核，但：

- 咨询类意图走对话链路
- `交易指令` 是 `high risk`，强制 `case mode`
- 模型不能直接下单，必须经过适当性校验、二次确认和 HITL

---

## 6. 意图路由内部流程

### 6.1 shadow 模式（当前默认）

```text
Request ──▶ LLM 主路由 ──▶ RouteDecision ──▶ 返回
                │
                └─ JEV 影子并行 ──▶ shadow{domain, intent, confidence, agreement}
                                   只记录，不影响返回结果
```

适用场景：中文为主、JEV 中文效果尚未达标。  
作用：线上稳定，同时积累 JEV 的真实对比数据。

### 6.2 hybrid 模式（中文评测达标后）

```text
Request ──▶ JEV 主路由 ──▶ confidence / margin 足够？ ──是──▶ 返回
                │
                └─ 否 / 异常 ──▶ LLM 兜底 ──▶ 返回
```

适用场景：JEV 在中文评测集上达到门槛，希望降低对通用大模型的依赖。  
作用：JEV 负责大多数请求，LLM 只处理低置信和异常。

### 6.3 阈值与澄清

默认阈值：

```text
confidence >= 0.8
margin     >= 0.2
```

含义：

- `confidence` 低于阈值 → `needs_clarification = true`
- 第一候选与第二候选的差值 `margin` 太小 → 也视为不确定
- 上层可以选择“追问澄清”，而不是硬猜

可通过以下环境变量调整：

```text
INTENT_CONFIDENCE_THRESHOLD=0.8
INTENT_MARGIN_THRESHOLD=0.2
```

---

## 7. 当前落地状态

| 模块 | 状态 |
|---|---|
| `platform/intent/contracts.py` | `[新增]` 已落地：`IntentRequest`、`RouteDecision`、`DomainManifest`、`IntentClassifier` |
| `platform/intent/registry.py` | `[新增]` 已落地：从 `configs/domains.yaml` 加载领域 |
| `platform/intent/jev.py` | `[新增]` 已落地：JEV 适配器、脱敏、可选翻译、置信度 / 边界纠正 |
| `platform/intent/llm.py` | `[新增]` 已落地：LLM 主路由、可选翻译器 |
| `platform/intent/hybrid.py` | `[新增]` 已落地：主路由 + 兜底 + 影子 |
| `platform/intent/factory.py` | `[新增]` 已落地：`shadow / hybrid / jev / llm` 四种预设 |
| `configs/domains.yaml` | `[新增]` 已落地：claims / investment / general 三领域清单 |
| `scripts/eval_intent.py` | `[新增]` 已落地：准确率、混淆矩阵、兜底率、影子一致性、延迟 |
| `data/intent_golden.jsonl` | `[新增]` 已落地：中英混合合成评测集 |
| `app.py` 接入 IntentRouter | `[规划]` 未接入，现有理赔链路保持原样 |
| `ClaimsPlugin` 包装 | `[规划]` 待做 |
| `Investment / General` 图实现 | `[规划]` 待做 |
| Redis / Celery / Kafka 等外部适配器 | `[规划]` 待做 |
| Outbox 闭环 | `[规划]` 当前未闭环 |

### 当前状态 vs 目标

| 环节 | 当前 | 目标 |
|---|---|---|
| 入口 | `/assistant/stream` + `/claims/*` | 统一入口 + 领域路由 |
| 意图识别 | `assistant_agent` 内部 `classify` | `IntentRouter`（LLM/JEV/Hybrid） |
| 领域 | 只有理赔 | claims / investment / general |
| 状态 | 进程内 checkpointer | `StateStore` SPI（Redis/Postgres） |
| 队列 | 同步长请求 | `TaskQueue`（Celery/Arq） |
| 事件 | Outbox 未闭环 | `EventBus` / Outbox |
| 模型 | 两套路由 | `ModelGateway` 统一 |
| 观测 | Langfuse / 日志 | + 意图影子报告 / 指标 |

---

## 8. 扩展方式

### 8.1 新增一个领域

```text
1. 在 configs/domains.yaml 增加领域清单
2. 实现一个 DomainPlugin：
     manifest + graph + capabilities
3. 注册 entry point / 配置
4. 增加领域一致性测试
```

目标是：**内核不改，只加插件。**

### 8.2 新增一种意图引擎

```text
1. 实现 IntentClassifier.classify()
2. 在 factory 的预设里组合：
     primary / fallback / shadow
3. 用 scripts/eval_intent.py 做对比评测
```

目标是：**领域不改，只换引擎。**

### 8.3 替换基础设施

```text
1. 实现对应的 Capability SPI
2. 在启动时注入
3. 领域图不改
```

例如：

```text
StateStore:   InMemory → Redis / Postgres
TaskQueue:    Inline   → Celery / Arq / Kafka
Lock:         InProcess→ Redis
RateLimiter:  InProcess→ Redis
EventBus:     InProcess→ Kafka / RabbitMQ
Outbox:       未闭环  → DB Outbox + 重试
ObjectStore:  Local    → S3 / OSS
```

---

## 9. 关键文件与配置

| 路径 | 作用 |
|---|---|
| `app.py` | FastAPI 入口、SSE、理赔接口 |
| `agents/assistant_agent.py` | 理赔对话图：`classify` / `material_gate` / `formal_review` |
| `agents/claim_agent.py` | 理赔案件状态机、三专家、`route_decision` |
| `agents/middleware_audit.py` | PII 脱敏、限流、缓存、审计、HITL |
| `config.py` | 模型工厂与现有两套路由 |
| `settings.py` | 环境配置，含新增的 `INTENT_*` / `JEV_*` |
| `platform/intent/` | 新增的意图路由公共层 |
| `configs/domains.yaml` | 领域清单，单一事实源 |
| `scripts/eval_intent.py` | 意图评测脚本 |
| `data/intent_golden.jsonl` | 意图评测数据 |

> 注意：领域配置目录使用 `configs/`，不是 `config/`，避免和项目根目录的 `config.py` 同名冲突。

### 常用评测命令

```bash
# JEV 单引擎
python -m scripts.eval_intent --engine jev --data data/intent_golden.jsonl

# 影子模式：LLM 主路由 + JEV 只记录
python -m scripts.eval_intent --engine shadow --limit 20

# 混合模式：JEV 主 + LLM 兜底
python -m scripts.eval_intent --engine hybrid --min-accuracy 0.9

# JEV 前先翻译成英文
python -m scripts.eval_intent --engine jev --translate
```

---

## 10. 术语表

| 术语 | 含义 |
|---|---|
| Domain | 业务领域，如 claims / investment / general |
| Intent | 领域内具体意图，如“理赔报案”“组合诊断” |
| IntentRouter | 统一意图路由，输出 domain + intent |
| RouteDecision | 路由结果，含置信度、margin、是否澄清 |
| DomainRegistry | 领域注册表，从 YAML 加载并校验 |
| DomainPlugin | 领域插件，承载该领域的图与能力 |
| Capability SPI | 可插拔能力接口，如状态、队列、锁、事件 |
| HITL | Human In The Loop，人工审核 |
| Outbox | 事务性事件发件箱，保证事件不丢 |
| Shadow | 影子模式，候选引擎只记录不生效 |
| Hybrid | 混合模式，主引擎 + 兜底引擎 |
| JEV | `ateve-jev-v1` 意图识别模型 |
| margin | 第一候选与第二候选的概率差 |

---

## 11. 注意事项

1. **当前 `app.py` 还没有接入新的 `IntentRouter`**  
   现有理赔链路保持原样，避免破坏已有测试和线上行为。

2. **JEV 当前中文效果不稳定**  
   中文同义句可能被分到 general，因此默认使用 `shadow`，不要直接全量接管。

3. **API Key 只从环境变量读取**  
   `JEV_API_KEY` 不写入仓库、不写入报告、不打印日志。已经暴露过的 key 应尽快轮换。

4. **高风险意图必须走 HITL**  
   例如投资域的“交易指令”，即使模型置信度很高，也不能跳过适当性校验和人工审批。

5. **对话链路和案件链路不是二选一**  
   它们是同一平台里的两种执行模式：轻问答走对话图，长事务 / 高风险走案件状态机。

---

## 12. 一页纸总结

```text
用户请求
  ↓
FastAPI 接入
  ↓
中间件：鉴权 / 限流 / 脱敏 / 审计
  ↓
IntentRouter：domain + intent + confidence
  ↓
DomainRegistry：校验领域与意图
  ↓
DomainPlugin：claims / investment / general
  ↓
LangGraph：对话图 或 案件状态机
  ↓
RAG / 三专家 / 工具 / HITL
  ↓
SSE 返回 + Outbox 事件 + 观测指标
```

**一句话：统一入口做分诊，领域插件做业务，Capability SPI 做水平扩展。**
