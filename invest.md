【前端层】  
智能工作台 UI（投资问答 / 组合诊断 / 风险评估 / 产品查询 / 交易确认 / 链路可视化）  
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
/api/assistant/stream                          -> 链路① 对话投资问答  
/api/investment/process · confirm · review     -> 链路② 投资域图  
/api/investment/rag/search                     -> 投资知识库检索  
/health · /ready · /metrics                    -> 存活 / 就绪 / 指标  
|  
v  
【编排层】  
链路① 对话投资问答(LangGraph) : classify(IntentRouter: JEV/LLM/Hybrid) -> investment_rag -> investment 模型（外层流式）  
链路② 投资域图(LangGraph)     : intake -> context -> risk -> review/advise -> execute/rejected/terminal  
└ 敏感指令                : 二次确认 -> 人工审批 -> 适配器执行 / 不执行  
|  
v  
【服务层】  
InvestmentServices（portfolio / product / market / execute）  
InvestmentRAG（投资 Wiki：BM25 + BGE-M3/Milvus + metadata -> 加权 RRF -> BGE-Reranker）  
|  
v  
【适配器层】  
InvestmentBackend -> 券商 / 基金 / 行情适配器（当前未接真实下单）  
DemoInvestmentBackend -> 合成组合 / 产品 / 行情  
|  
v  
【模型层】  
plus（投资问答 / 投资建议）· max（投资风险 / 交易档位，当前投资图规则计算不调用 LLM）  
JEV（对话入口意图分类，ateve-jev-v1，英文优先）  
|  
v  
【数据层】  
SQLite : checkpoints.sqlite（投资图检查点）  
audit.sqlite     （请求审计，只追加 + 哈希链）  
outbox.sqlite    （回写队列；组件已实现，主图未注入）  
Milvus  : investment_wiki（投资 Wiki 向量集合）  
Redis   : 会话历史（可选）  
日志    : .data/logs/app.log · .data/logs/uvicorn.log

【横切】 接入层：RequestID / 认证 / 限流 / 审计；意图路由：JEV / LLM / Hybrid / Shadow；  
RAG：多路召回 / RRF / rerank / 引用校验；观测：Prometheus / LangFuse / stdout JSON
