"""
第 1 课：跟大模型说上第一句话
================================

一句话理解：大模型(LLM) 本质就是一个"能聊天的函数"。
    输入(文字)  ->  [ 模型 ]  ->  输出(文字)

调用它需要三个要素（缺一不可）：
  1. base_url —— 模型服务器的"地址"（服务在哪）
  2. api_key  —— 你的"门禁卡"（证明身份 + 计费，绝不能写进代码/提交到 git）
  3. model    —— 用哪个"模型"（比如 deepseek-flash）

本文件用你的 .env 里已配好的 DeepSeek 做演示。
"""

import os
import sys
from pathlib import Path

# 本文件在 my_study/ 子目录里，而 config.py 在项目根目录；
# 下面这行把"项目根目录"加进 Python 的查找路径，才能 import config。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv            # 用来读取 .env 文件的库
from langchain_openai import ChatOpenAI   # LangChain 的 OpenAI 兼容聊天客户端

# 把 .env 里的配置加载成环境变量，这样 os.getenv(...) 才读得到。
load_dotenv()

# ========== 方式 A：最原始，自己拼三个要素 ==========
llm = ChatOpenAI(
    model="deepseek-flash",                 # 用哪个模型
    base_url="https://api.deepseek.com",    # 地址
    api_key=os.getenv("DEEPSEEK_API_KEY"),  # 门禁卡：从 .env 读，绝不写死
)

reply = llm.invoke("你好，请用一句话介绍你自己。")  # invoke = 调用一次
print("模型说：", reply.content)                     # .content = 模型说的话


# ========== 方式 B：老师项目里其实已经帮你封装好了 ==========
# 打开 config.py 看 ClaimLLMFactory，它内部就是"方式 A"在帮你拼这三个要素。
from config import ClaimLLMFactory

model = ClaimLLMFactory.create("main")   # "main" 是一个档位（见 config.py 的 profiles）
reply2 = model.invoke("用一句话说说：什么是理赔？")
print("模型说：", reply2.content)
