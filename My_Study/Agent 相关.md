## 为什么需要 Rerank？
Embedding 召回属于双编码器（Bi-Encoder）方案：问题和文档分别编码成向量，仅依靠向量相似度检索。优点是速度快，但**缺少 query 与文档 token 级的交叉交互**，容易召回 “语义相似但不回答问题” 的片段。
Rerank 一般用交叉编码器（Cross-Encoder），将**Query 和候选文档拼接成对输入**，让模型直接判断该文档和当前问题的相关性，基于真实语义匹配重新排序，过滤假阳性结果，提升 RAG 答案质量。



## RAG 如何保证 100%正确
核心观点：**RAG 不可能做到 100% 准确，根源是 LLM 本身存在模型幻觉，整套系统要分层设计来控制风险**

#### ① 前提层：RAG 不可能 100% 准确

根本原因：**LLM 大模型本身自带幻觉问题**，RAG 只是检索增强，不能彻底消除幻觉。

#### ② 架构层（检索 + 生成两大模块）

1. **检索模块**
   - 混合检索：**切片 + 元数据**组合检索（关键词 + 向量等多路召回）
2. **生成模块**
   - 提示词工程
   - 随机性：`Temperature` 温度参数控制输出创造性
   - 抽取 JSON 结构化输出

#### ③ 防护层（风险拦截）
- 小 LLM 幻觉检测：用轻量模型校验大模型输出，识别幻觉内容
- 界面可视：溯源引用来源，让用户看到引用原文
- 关键词检查：敏感 / 错误关键词过滤拦截

#### ④ 兜底层（最终保障）
- 提升回答门槛：不确定的内容不强行作答
- 人工复核：高风险场景人工审核
- 全链路日志：完整记录检索、输入、输出链路，便于排查问题

#### 一句话总结
RAG 系统不是单靠向量检索 + 大模型生成，而是一套**四层风控体系**：承认 LLM 幻觉的固有缺陷，从检索生成架构、实时内容防护、事后人工 + 日志兜底，层层降低错误输出，而不是追求绝对 100% 正确。



# 一、 苏格拉底提问法（苏格拉底方法 / 助产术）

**一句话定义：不直接给答案，通过连续、结构化提问，引导对方自己发现观点里的矛盾、审视隐藏假设，自主推导出结论的批判性思维对话方法，也叫助产术**

# 二、现代常用 6 大类提问模板（实战可用）

1. **澄清类**（搞懂概念）
你这句话是什么意思？能不能举个例子？
2. **探查隐含假设**（挖出没说出口的前提）
你这个结论背后，默认了什么前提？这个假设一定成立吗？
3. **证据与理由类**（验证支撑）
你凭什么这么认为？有什么证据 / 数据支持？有没有反例？
4. **多角度视角类**
换一个立场，别人会怎么看待这件事？
5. **推论与后果类**
如果这个观点成立，会带来什么结果？长期影响是什么？
6. **元思考类**
我们现在讨论的核心问题是什么？我们有没有偏离主题？

## 三、关键特点（容易踩坑的误区）

✅ 目标：**共同探索，不是辩论赢对方、不是拷问审问**
✅ 姿态：提问者不必预设标准答案
❌ 误区：不是抬杠、不是连环质问刁难人；不是为了证明对方错

## 四、结合你前面 RAG 场景举个例子

> 
> 观点：RAG 可以做到 100% 回答准确
> 苏格拉底式提问：

1. 你说的 “100% 准确”，定义是什么？是完全没有幻觉？
2. 你假设 LLM 不会产生幻觉，这个假设成立吗？
3. 有什么证据证明 RAG 可以消除大模型幻觉？
4. 如果 RAG 一定 100% 准确，那为什么行业要做防护层、人工复核？
5. 如果 LLM 幻觉无法根除，那 RAG 系统的目标应该是什么？

## 五、应用场景

# 六、RAG 全链路检查与日志落盘

## 1. 检查结论

RAG 主链路符合预期：

```text
意图识别 → 多路召回 → 加权 RRF → BGE-Reranker 精排 → Top-K → 引用校验
```

最新验证请求（`/api/assistant/stream`，问题：`投资基础知识`）：

| 项目 | 结果 |
|---|---|
| 意图识别 | `投资咨询` |
| HTTP 状态 | 200 |
| 总耗时 | 约 12.8s |
| `vector_ready` | `true` |
| `corpus_size` | 55 |
| dense / bm25 / metadata 命中 | 16 / 16 / 16 |
| `route_errors` | `{}` |
| `fused_count` | 27 |
| `rerank_candidates` | 20 |
| `reranked` | `true` |
| `rerank_fallback` | `false` |
| 返回条数 | 4 |

说明：

- 三路召回都正常，没有单路报错。
- 27 条融合候选中有 20 条进入 BGE-Reranker，符合 `RERANK_TOP_N=20` 的配置。
- `rerank_fallback=false` 表示实际使用了 BGE-Reranker，没有退化成词项重排。
- Top-1 是正文块，不再是标题/免责声明块；也没有 `参考资料` 块进入 Top-K。
- 回答引用 `[K1]`～`[K4]` 全部来自本轮检索结果，没有非法引用。
- K2/K4 偏合规和防诈骗，但对“投资基础知识”这类宽泛问题，回答把它们用在了风险提示和平台核实部分，属于可接受结果。

## 2. 日志落盘位置

当前开发机统一放在：

```text
.data/logs/app.log        # 应用日志，含 rag.retrieval
.data/logs/uvicorn.log    # uvicorn 启动/访问/异常日志
.data/audit.sqlite        # 审计库，含 details.retrieval
.data/milvus.db/          # 本地 Milvus Lite 数据
```

为什么不放 `/tmp`：

- 重启或系统清理后容易丢。
- 排查 RAG、模型调用、审计问题时需要长期保留。

为什么不放项目根目录：

- 容易误提交。
- `.data/` 已经在 `.gitignore` 中，适合放运行期数据。

## 3. 日志配置

`.env` 或 `.env.example`：

```dotenv
LOG_LEVEL=INFO
LOG_FILE=.data/logs/app.log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
# LOG_JSON=true
```

含义：

- `LOG_FILE`：应用日志文件；父目录不存在会自动创建。
- `LOG_MAX_BYTES`：单个日志文件上限，默认 10MB；设为 `0` 关闭轮转。
- `LOG_BACKUP_COUNT`：保留的历史日志份数，默认 5。
- `LOG_JSON=true`：输出 JSON Lines，适合 Loki/ELK 等采集。
- 日志文件不可写时会退回 stderr，不阻断服务启动。

`logging_setup.py` 使用 `RotatingFileHandler`，因此本地开发不依赖外部 logrotate。

## 4. 启动方式

推荐使用：

```bash
bash scripts/start_mac.sh
```

脚本会：

1. 自动创建 `.data/logs/`。
2. 从 `.env` 读取 `LOG_FILE`。
3. 把应用日志写入 `.data/logs/app.log`。
4. 把 uvicorn 输出同时 tee 到 `.data/logs/uvicorn.log`。

手动启动时如果要同时落盘：

```bash
mkdir -p .data/logs

LOG_FILE=.data/logs/app.log \
uvicorn app:app --host 127.0.0.1 --port 8001 --reload \
  2>&1 | tee -a .data/logs/uvicorn.log
```

注意：修改 `.env` 后必须重启 uvicorn 才会生效。

## 5. 查看日志

实时查看应用日志：

```bash
tail -f .data/logs/app.log
```

实时查看 uvicorn 日志：

```bash
tail -f .data/logs/uvicorn.log
```

只查 RAG 检索诊断：

```bash
grep 'rag.retrieval' .data/logs/app.log
```

查最新审计事件：

```bash
sqlite3 .data/audit.sqlite \
  "select id, resource, status, latency_ms from audit_events order by id desc limit 5;"
```

查审计里的检索详情：

```bash
sqlite3 -json .data/audit.sqlite \
  "select details from audit_events where resource='/api/investment/rag/search' order by id desc limit 1;"
```

## 6. 生产环境建议

- 裸机 / systemd：
  - 应用日志放 `/var/log/claims-ai-agent/app.log`
  - uvicorn 日志放 `/var/log/claims-ai-agent/uvicorn.log`
  - 审计库放 `/var/lib/claims-ai-agent/audit.sqlite`
- Docker / Kubernetes：
  - 不要把日志只写到容器文件系统
  - 输出到 stdout/stderr，设置 `LOG_JSON=true`
  - 交给 Loki / ELK / CloudWatch 等采集
- 日志目录权限建议 `0750`，日志文件 `0640`。
- 审计库和日志分开管理，审计保留周期通常应长于应用日志。