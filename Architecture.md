# 理赔 Agent 架构

## 一、全景分层架构

```
【前端层】
  理赔工作台 UI（聊天 / 单证上传 / 链路可视化）
       |
       v   HTTP / SSE
【路由层】 app.py (FastAPI) —— 纯 URL 静态匹配，无大模型
  /api/assistant/stream                     -> 链路① 对话助手
  /api/claims/process · supplement · review · {id}  -> 链路② 理赔状态机
  /api/documents/analyze                    -> 单证识别
  /api/demo/claims/process                  -> 演示（复用链路②）
  /health · /metrics
       |
       v
【编排层】
  链路① 对话助手(LangGraph) : classify -> policy_query / material_gate -> follow_up（回答外层流式）
  链路② 理赔状态机(LangGraph) : intake -> policy -> 三专家 -> confidence -> decision
  链路③ 工具Agent   : AgentExecutor + 8工具（isolated_deep，未接主 app）
       |
       v
【服务层】
  WorkflowServices（policy / verify / expert）
  MiddlewareChain（限流 -> 脱敏 -> 缓存 -> 推理 -> 审计 -> HITL）
       |
       v
【适配器层】
  BusinessBackend -> CoreSystemAdapter（HTTP + 熔断 + 只读缓存）-> 核心系统
  DemoBackend     -> PolicyStore（SQLite: policies.sqlite）
       |
       v
【模型层】
  flash（分类/轻量）· plus（通用/客服）· max（专家/强推理）· vision（单证视觉）
       |
       v
【数据层】
  SQLite : checkpoints.sqlite（状态机检查点）
           policies.sqlite  （本地保单，新增）
           outbox.sqlite    （赔付/通知回写队列）
  Redis（会话历史，可选）· Milvus（条款向量，可选）· 核心系统 HTTP（真实保单）

【横切】 认证 · mask_pii 脱敏 · 限流 · 审计 · LangFuse / Prometheus
```

## 二、入口路由：两层，只有一层有大模型判断

```
HTTP 路由（无模型，静态 URL 匹配）
  /api/assistant/stream  /api/claims/*  /api/documents/analyze ...
        │
        ▼
意图路由（flash 大模型判断）  <-- 大模型入口在这里
```

1. **HTTP 层路由**（FastAPI 装饰器）—— 纯 URL 匹配，请求打到哪个 endpoint 是写死的，**没有大模型**。
2. **对话助手内部「意图路由」** —— 进入 `/api/assistant/stream` 后，先调 flash 大模型做意图分类，再按结果分流：

```
用户消息 + 附件 + 历史
  -> 意图分类（flash 大模型）   <-- 大模型判断入口
       输出: intent + confidence + policy_id（保单号也由它抽取）
  -> 按 intent 分流
       |-- 一般咨询     -> general 模型
       |-- 保单查询     -> 查后端（PolicyStore / CoreSystemAdapter）
       |-- 其他理赔意图 -> customer_service 模型（材料门控在前）
```

对应代码：

```python
classifier = intent_model or get_model('classification')   # flash / deepseek-flash
intent_response = await classifier.ainvoke(...)            # 大模型判断
intent = IntentResult.model_validate_json(raw_intent)      # intent + confidence + policy_id
stage = 'general' if intent.intent == '一般咨询' else 'claims'
```

## 三、链路① 对话助手（LangGraph 多节点，/api/assistant/stream）

方案 A：无状态多节点图（`agents/assistant_agent.py`）。图负责编排决策，LLM 流式回答由外层执行器负责。

```
START
  -> classify（意图分类 flash 大模型 -> intent + confidence + policy_id）
  -> 条件路由
       |-- 一般咨询  -> END（外层流式 general 回答）
       |-- 保单查询  -> policy_query -> END（反问保单号 / 输出保单摘要）
       |-- 其他理赔  -> material_gate
                          |-- 缺材料 -> follow_up -> END（回流追问，最多 3 轮 -> 转人工）
                          |-- 齐全   -> END（外层流式 claims 回答）
```

**节点职责**

| 节点 | 职责 |
|---|---|
| classify | 意图分类 + 路由决策 + 构建回答 messages |
| policy_query | 查保单（PolicyStore / CoreSystemAdapter），缺保单号反问，降级/失败转人工 |
| material_gate | 材料完整性门控 + 提取结构化字段（claim_id / policy_id / amount） |
| follow_up | 回流追问，最多 3 轮，超限转人工 |

**外层执行器**（`app.py` 的 `assistant_stream`）

```
ainvoke 图 -> 重放 events（trace + intent + material_status + content）-> 流式 LLM 回答 -> done
```

> 链路① 只做「对话预审」，不触发正式核赔（trace 中明确标注"未调用业务保单接口"）。
> 当前为方案 A（无状态，每次请求新建图）；方案 B（checkpointer + interrupt 断点续跑）见 README。

## 四、链路② 理赔状态机（LangGraph，/api/claims/*）

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
                      -> experts（Send 扇出，并行）
                            |-- damage    损失专家
                            |-- risk      风险专家
                            |-- liability 责任专家
                      -> aggregate（置信度 = min(三专家)）
                      -> route_decision（业务规则优先于模型分数）
                            |-- 高风险                -> investigate 调查
                            |-- 大额 / 低置信 / 缺证据 -> review 转人工（interrupt 挂起等 /review）
                            |-- 通过                  -> auto 受理建议（不执行付款）
  -> END
```

## 五、大模型判断位置汇总

| 环节 | 模型档位 | 作用 |
|---|---|---|
| 意图分类（入口路由） | flash | 判断用户意图 + 抽保单号 |
| 单证识别 | vision / plus | 识别上传的发票/病历/事故单 |
| 三专家 | max | 损失/风险/责任判断 |
| 回答生成 | plus | 客服/通用回答 |

## 六、三处 SQLite 职责

```
checkpoints.sqlite  <- 链路② 状态机断点/恢复（AsyncSqliteSaver）
policies.sqlite     <- 链路① 保单查询的本地模拟数据（PolicyStore）
outbox.sqlite       <- 赔付/通知回写队列（Outbox，入队 ≠ 付款）
```
