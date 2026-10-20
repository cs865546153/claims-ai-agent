# Stage 6 · Agent 核心机制

> 目标：不依赖 LangChain/LangGraph，手写一个可测试的 Agent Loop。理解框架到底帮你做了什么。
> 预计：5 天 + 第 6 周项目实战。

---

## 1. LLM 调用与 messages

OpenAI 兼容接口（DeepSeek / Qwen / 本地模型）的核心结构：

```python
from openai import OpenAI

client = OpenAI(base_url="https://api.deepseek.com", api_key="...")

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "你是理赔助手，只回答与理赔相关的问题。"},
        {"role": "user", "content": "CLM-2024-001 现在什么状态？"},
    ],
    temperature=0.2,
)

print(response.choices[0].message.content)
print(response.usage.prompt_tokens, response.usage.completion_tokens)
```

| 角色 | 作用 | 注意 |
|---|---|---|
| `system` | 设定身份、边界、输出格式 | 放在最前，通常始终保留 |
| `user` | 用户输入 | 可包含检索到的资料（RAG） |
| `assistant` | 模型回复 | 带 `tool_calls` 时 `content` 常为 `None` |
| `tool` | 工具执行结果 | 必须带 `tool_call_id`，紧跟在 assistant 之后 |

**参数速记**

| 参数 | 作用 | 建议 |
|---|---|---|
| `temperature` | 随机性 | 抽取/分类 0~0.2；创意写作 0.7+ |
| `max_tokens` | 输出上限 | 按场景设，防止跑飞 |
| `tools` | 可用工具列表 | 只给当前任务需要的 |
| `tool_choice` | 是否强制调用 | 默认 `auto` |
| `response_format` | 结构化输出 | JSON mode / JSON schema |

---

## 2. 工具 schema（Function Calling）

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_claim_status",
            "description": "根据理赔单号查询当前状态。只读操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "理赔单号，例如 CLM-2024-001",
                    }
                },
                "required": ["claim_id"],
                "additionalProperties": False,
            },
        },
    }
]
```

**写好工具描述的三个要点**

1. **description 写"什么时候用"**，不只是"是什么"。
2. 参数 description 写格式和例子（模型靠这个填参数）。
3. 不要让模型猜：枚举值写 `enum`，必填写 `required`。

> 对比：pydantic 的 `model_json_schema()` 可以直接生成 parameters。

---

## 3. 模型返回的工具调用

```python
{
    "role": "assistant",
    "content": None,
    "tool_calls": [
        {
            "id": "call_abc123",
            "type": "function",
            "function": {
                "name": "get_claim_status",
                "arguments": '{"claim_id": "CLM-2024-001"}',
            },
        }
    ],
}
```

注意：

- `arguments` 是 **JSON 字符串**，不是 dict。可能为空串、可能不合法。
- `id` 用来和 tool 结果配对，不能丢。
- 一次可能返回多个 `tool_calls`（并行工具调用）。

执行后追加：

```python
{
    "role": "tool",
    "tool_call_id": "call_abc123",
    "name": "get_claim_status",
    "content": '{"claim_id": "CLM-2024-001", "status": "reviewing"}',
}
```

`content` **必须是字符串**。工具返回 dict 时要 `json.dumps`。

---

## 4. Agent Loop

```python
def run_agent_loop(llm, user_message, registry, system_prompt="...", max_steps=8):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for _ in range(max_steps):
        reply = llm(messages)          # 返回 assistant message dict
        messages.append(reply)

        tool_calls = reply.get("tool_calls") or []
        if not tool_calls:
            return messages            # 最终回答

        for call in tool_calls:
            fn = call["function"]
            content = dispatch(call["name"], fn.get("arguments"), registry)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": fn["name"],
                    "content": content,
                }
            )

    raise AgentLoopError(f"超过 {max_steps} 步仍未结束")
```

**必须有**

- `max_steps`：防死循环（模型可能反复调同一个工具）。
- 工具异常转错误字符串：让模型看到"失败原因"并自我修正。
- 参数校验：模型经常给错参数名/类型。
- 日志：每轮记录工具名、参数（截断）、耗时、结果长度。

**终止条件**：模型不再返回 `tool_calls`（通常同时有 `content`）。
不要用"content 为空"判断，模型有时两者都为空。

---

## 5. 结构化输出

让模型稳定返回 JSON 的三种方式（从弱到强）：

1. Prompt 里写"只返回 JSON"（最不可靠）。
2. `response_format={"type": "json_object"}`（JSON mode，保证是 JSON，不保证 schema）。
3. `response_format={"type": "json_schema", ...}` 或工具调用 + pydantic 校验（最可靠）。

```python
from pydantic import BaseModel, Field

class AgentAnswer(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)

answer = AgentAnswer.model_validate_json(raw_json)
```

**永远不要相信模型输出的格式**：即使开了 JSON mode，也要校验；校验失败就重试或降级。

---

## 6. 上下文预算

上下文窗口有限，对话越长越贵、越慢。

策略（按优先级）：

1. **裁剪**：保留 system + 最近 N 条（第 24 天练习）。
2. **摘要**：把旧对话压缩成一段摘要。
3. **检索**：只把相关片段放进 prompt（RAG），不要全量塞。
4. **结构化**：用状态对象保存关键信息，而不是把全文反复带上。

**坑**：裁剪时不要拆散 `assistant(tool_calls)` 和对应的 `tool` 消息，否则 API 直接 400。

---

## 7. 流式、HITL、可观测性（了解）

| 能力 | 关键点 |
|---|---|
| 流式 | `stream=True`，逐 chunk 输出；流式中途失败不能重试 |
| HITL（人工介入） | 高风险动作（退款、批改）先暂停，等人工确认 |
| 幂等 | 工具要有幂等键，重试不重复扣款/重复建单 |
| 追踪 | 每次请求一个 `trace_id`，记录每轮模型调用与工具调用 |
| 成本 | 统计 token、模型单价、每单成本；小模型先行，必要时升级 |
| 评测 | 固定数据集 + 断言，不靠"感觉变好了" |

---

## 8. 手写 Loop vs LangGraph（项目对照）

| 手写 Loop | LangGraph |
|---|---|
| `messages` 列表 | `State`（TypedDict） |
| 一个 `for` 循环 | 节点 + 边 |
| `if tool_calls` | 条件边 |
| 自己控制步数 | 图结构 + recursion limit |
| 自己存历史 | Checkpointer（内存/SQLite/Postgres） |
| 自己实现中断 | `interrupt()` + `Command(resume=...)` |

**先手写，再用框架**：否则出了问题不知道是模型、prompt 还是框架的锅。

---

## 9. 常见坑

1. `arguments` 当 dict 用，没 `json.loads`。
2. `tool` 消息丢了 `tool_call_id`，或顺序错乱。
3. 工具抛异常直接冒泡，整个请求 500。
4. 没有 `max_steps`，模型死循环烧钱。
5. 把完整工具结果（几 MB）塞回上下文。
6. system prompt 里塞了密钥/内部 URL。
7. 用 `content is None` 判断结束（应该看 `tool_calls`）。
8. 流式接口后面又加了重试，导致重复输出。

---

## 10. 本阶段练习

| 函数 | 练什么 | 对应项目 |
|---|---|---|
| `build_tool_schema` | JSON Schema、参数校验 | `tools/` 的工具定义 |
| `dispatch_tool_call` | JSON 解析、异常兜底 | 工具执行层 |
| `run_agent_loop` | 消息流转、终止条件 | `agents/claim_agent.py` |
| `truncate_messages` | token 预算 | `memory.py` |

验收：

```powershell
.\.venv\Scripts\python.exe -m pytest stage6_agent -q
```

全部通过后运行综合示例：

```powershell
# 离线：用假 LLM 跑完整 Loop，打印消息流
.\.venv\Scripts\python.exe stage6_agent\capstone_mini_agent.py

# 在线：真实调用（需要项目根目录 .env 里有 DEEPSEEK_API_KEY）
.\.venv\Scripts\python.exe stage6_agent\capstone_mini_agent.py --real
```

**自检问题**

1. 模型返回 `tool_calls` 时，`content` 通常是什么？为什么？
2. 为什么工具错误要转成字符串返回，而不是抛异常？
3. `max_steps` 应该设多少？依据是什么？
4. 上下文裁剪时，为什么不能只保留最后 N 条？
