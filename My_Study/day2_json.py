"""
第 2 课：提示词 + 让模型输出严格的 JSON
========================================
上一课我们只会让模型"随便说一句话"。但要让 Agent 干活，必须让它输出
"结构化"的结果——也就是机器能直接解析的 JSON，而不是一段大白话。

今天三个新概念：
  1. system 提示词 —— 给模型"定规矩 / 定人设"（它会在整段对话里一直记着）
  2. human 提示词  —— 你这一次具体问它什么
  3. 结构化输出(JSON) —— 告诉模型"只能输出 JSON，别加废话"，然后我们用 json.loads 解析

JSON 长这样： {"字段": "值", ...}；Python 里 json.loads() 能把它变成字典(dict)。
"""

import os
import sys
import json
from pathlib import Path

# 让脚本能找到项目根目录（那里有 .env）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# 显式读取项目根目录的 .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# 一个"会输出 JSON"的模型
llm = ChatOpenAI(
    model=os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-flash"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    temperature=0,   # 温度越低越稳定（0=几乎每次一样）；越高越"有创意"
    model_kwargs={"response_format": {"type": "json_object"}},  # 强制只输出 JSON
)

# 定规矩（system）
system = SystemMessage(content=(
    "你是理赔受理助手。把用户报案的理赔描述解析成一个 json 对象，字段必须是："
    "claim_type(险种)、amount(金额数字)、policy_id(保单号，没有就 null)、"
    "summary(一句话摘要)。只输出 json，不要输出任何解释或代码围栏。"
))

# 这次的具体输入（human）
human = HumanMessage(content="我的车在停车场被刮了，修车花了 3200 元，保单号 POL-2024-001。")

reply = llm.invoke([system, human])
print("模型原始输出：", reply.content)

# 把 JSON 字符串变成 Python 字典
data = json.loads(reply.content)
print("解析后的类型：", type(data).__name__)
print("险种：", data["claim_type"])
print("金额：", data["amount"])
print("保单号：", data["policy_id"])
print("摘要：", data["summary"])
