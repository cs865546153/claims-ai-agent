"""
第 5 课：任务编排的核心 —— 状态机 + 图（LangGraph）
====================================================
"任务编排"就是把一件大任务，拆成若干"步骤(节点)"，用"箭头(边)"连成一张流程图，
每个节点可以改一份共享的"状态(state)"，还能按条件走不同分支。

四个核心词：
  - State(状态)    —— 一份在流程里流动的"数据字典"
  - Node(节点)     —— 一个步骤，是个函数：收 state -> 返回要更新的字段
  - Edge(边)       —— 箭头，决定下一步去哪个节点
  - 条件路由        —— 根据 state 判断走哪条分支（就像 if/else）

今天我们用"纯 Python、不调用大模型"的方式，搭一个最小的理赔流程图：
  报案 → 查保单 → 路由(金额>50000 转人工，否则自动通过) → 结束
这样你能清清楚楚看到图是怎么转起来的。
"""

import sys
from pathlib import Path
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import StateGraph, START, END


# 1) 定义状态：一份字典，字段是流程里要用的数据
class ClaimState(TypedDict):
    claim_text: str
    policy_id: str
    amount: float
    policy_ok: bool
    decision: str


# 2) 定义节点：每个节点是一个函数，返回"要更新到状态里的字段"
def intake(state: ClaimState):
    # 报案：从文字里"假装"解析出保单号（真实项目这里让大模型做）
    return {"policy_id": "POL-2024-001"}


def policy(state: ClaimState):
    # 查保单：假装查到了（保单号以 POL 开头就算有效）
    return {"policy_ok": state["policy_id"].startswith("POL")}


# 3) 条件路由：根据状态返回"下一个节点名"
def route(state: ClaimState) -> str:
    if not state["policy_ok"]:
        return "reject"          # 保单无效 -> 拒绝
    if state["amount"] > 50000:
        return "review"          # 大额 -> 转人工
    return "auto"                # 否则 -> 自动通过


def auto(state: ClaimState):
    return {"decision": "自动受理"}


def review(state: ClaimState):
    return {"decision": "转人工复核"}


def reject(state: ClaimState):
    return {"decision": "拒赔(保单无效)"}


# 4) 组装图：把节点和箭头连起来
graph = StateGraph(ClaimState)
graph.add_node("intake", intake)
graph.add_node("policy", policy)
graph.add_node("auto", auto)
graph.add_node("review", review)
graph.add_node("reject", reject)

graph.add_edge(START, "intake")
graph.add_edge("intake", "policy")
# 条件路由：route 返回谁，就走谁；并声明可能的分支
graph.add_conditional_edges("policy", route, {"auto": "auto", "review": "review", "reject": "reject"})
for n in ("auto", "review", "reject"):
    graph.add_edge(n, END)

app = graph.compile()

# 5) 跑一次，看状态怎么流转
result = app.invoke({"claim_text": "车被刮，修车 3200 元", "amount": 3200.0})
print("最终状态：")
for k, v in result.items():
    print(f"  {k} = {v}")

# 小实验：把金额改大，看看会不会走"转人工"
print("\n（金额改成 80000 再跑一次）")
result2 = app.invoke({"claim_text": "车被刮，修车 80000 元", "amount": 80000.0})
print("  decision =", result2["decision"])
