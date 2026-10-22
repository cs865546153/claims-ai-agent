"""
第 3 课：工具（Tool）——让模型"会动手调函数"
============================================
大模型只能"说"，不能真的查数据库/调接口。怎么让它"动手"？
答案：把你写好的 Python 函数"注册"成工具，模型会输出"我想调用 XX 函数、参数是 YY"，
再由我们（或框架）替它真正执行这个函数，把结果喂回给模型。

一个工具 = 普通函数 + 一段"说明书"(docstring)，让模型知道它是干嘛的、参数是什么。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool          # @tool 装饰器：把普通函数变成"工具"
from langchain_core.messages import HumanMessage

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ---- 工具 1：查保单（假装有个数据库）----
@tool
def query_policy(policy_id: str) -> str:
    """根据保单号查询保单信息。参数 policy_id 是保单号，例如 POL-2024-001。"""
    fake_db = {
        "POL-2024-001": "车险，保额 50 万，状态：有效",
        "POL-2024-002": "医疗险，保额 20 万，状态：有效",
    }
    return fake_db.get(policy_id, "查无此保单")


# ---- 工具 2：算免赔额 ----
@tool
def deductible(amount: float) -> str:
    """根据理赔金额计算免赔额。参数 amount 是理赔金额(元)。返回需自付的免赔额。"""
    return f"免赔额 500 元，剩余可赔 {max(0.0, amount - 500)} 元"


# 把工具"绑定"给模型（bind_tools）
llm = ChatOpenAI(
    model=os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-flash"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0,
).bind_tools([query_policy, deductible])

# 用户问一个问题，模型可能决定"我要调用工具"
resp = llm.invoke([HumanMessage("帮我查一下保单 POL-2024-001 的信息。")])

print("模型是否想调用工具：", bool(resp.tool_calls))
for tc in resp.tool_calls:
    print("  想调用的函数：", tc["name"])
    print("  传的参数：", tc["args"])
    # 真正执行工具（现实里这一步就是"真正查数据库"）
    if tc["name"] == "query_policy":
        result = query_policy.invoke(tc["args"])
        print("  执行结果：", result)
