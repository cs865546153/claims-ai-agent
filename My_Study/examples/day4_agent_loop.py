"""
第 4 课：Agent 循环（ReAct）——思考 → 行动 → 观察 → ... 直到完成
================================================================
上一课模型只会"提出"要调用工具，但不会自己连续调用直到解决问题。
Agent 的核心就是那个循环：

    while 没结束:
        把消息发给模型
        if 模型想调用工具:
            执行工具 -> 把结果作为"观察"塞回消息 -> 继续循环
        else:
            模型给出了最终回答 -> 结束

这个模式叫 ReAct（Reason 推理 + Act 行动）。
今天我们不依赖任何框架，纯手写这个循环，把它彻底看懂。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@tool
def query_policy(policy_id: str) -> str:
    """根据保单号查询保单信息。参数 policy_id 是保单号，例如 POL-2024-001。"""
    fake_db = {"POL-2024-001": "车险，保额 50 万，状态：有效"}
    return fake_db.get(policy_id, "查无此保单")


@tool
def deductible(amount: float) -> str:
    """根据理赔金额计算免赔额。参数 amount 是理赔金额(元)。"""
    return f"免赔额 500 元，剩余可赔 {max(0.0, amount - 500)} 元"


tools = {"query_policy": query_policy, "deductible": deductible}

llm = ChatOpenAI(
    model=os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-flash"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0,
).bind_tools(list(tools.values()))


def run_agent(user_question: str, max_steps: int = 6) -> str:
    """手写的 Agent 循环。"""
    messages = [
        SystemMessage(content="你是理赔助手。需要查数据就先调用工具，拿到结果再回答用户。"),
        HumanMessage(content=user_question),
    ]
    for step in range(max_steps):
        resp = llm.invoke(messages)                 # 让模型"想一步"
        messages.append(resp)
        if not resp.tool_calls:                     # 模型不调用工具 = 它回答完了
            return resp.content
        for tc in resp.tool_calls:                  # 否则执行它想调用的每个工具
            print(f"[第{step + 1}步] 调用工具 {tc['name']}({tc['args']})")
            result = tools[tc["name"]].invoke(tc["args"])     # 真正执行
            # 把执行结果作为"观察"，告诉模型
            messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return "超过最大步数，仍未完成"


print("最终回答：", run_agent("我的保单 POL-2024-001 刮擦了，要赔 3200 元，能赔多少？"))
