"""
第 6 课：并行三专家 + 人机协同（HITL）
======================================
今天两个"高级"编排能力：

A. 并行（Send 扇出）：有些步骤互不依赖，可以同时做。
   比如理赔里"定损专家、风险专家、责任专家"可以三个一起跑，结果再汇总。
   关键词：Send（把一个节点扇出成多个）、operator.add（把多次返回"拼接"成列表）

B. 人机协同（HITL / interrupt）：有些决策不能全自动，必须暂停等人拍板。
   关键词：interrupt（暂停）、Command(resume=...)（人做决定后恢复）
   这正是老师项目里"补材料"和"大额转人工审核"的实现原理。
"""

import sys
import operator
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send, interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

# ================= A. 并行三专家 =================
class ExpertState(TypedDict):
    roles: list[str]
    # operator.add：同一个字段多次返回时，会自动"追加"到列表里（而不是覆盖）
    reports: Annotated[list[str], operator.add]


def dispatch(state: ExpertState) -> list[Send]:
    # 把一个专家节点，扇出成三份同时跑
    return [Send("expert", {"role": r}) for r in state["roles"]]


def expert(state: dict) -> dict:
    # 假装三个专家各自出报告（真实项目这里调用大模型）
    return {"reports": [f"{state['role']}专家：结论 A"]}


def summary(state: ExpertState) -> dict:
    return {"reports": [f"汇总：共 {len(state['reports'])} 份报告"]}


g1 = StateGraph(ExpertState)
g1.add_node("expert", expert)
g1.add_node("summary", summary)
g1.add_conditional_edges(START, dispatch, ["expert"])
g1.add_edge("expert", "summary")
g1.add_edge("summary", END)
app1 = g1.compile()

print("== A. 并行三专家 ==")
out1 = app1.invoke({"roles": ["定损", "风险", "责任"]})
for r in out1["reports"]:
    print("  ", r)

# ================= B. 人机协同（interrupt 暂停等人） =================
class ReviewState(TypedDict):
    amount: float
    decision: str


def review_node(state: ReviewState) -> dict:
    # 暂停，等人输入决定；resume 的值就是 interrupt 的返回值
    human = interrupt({"ask": f"金额 {state['amount']} 元，请人工决定", "choices": ["accept", "reject"]})
    return {"decision": human}


g2 = StateGraph(ReviewState)
g2.add_node("review", review_node)
g2.add_edge(START, "review")
g2.add_edge("review", END)
app2 = g2.compile(checkpointer=MemorySaver())   # 需要 checkpointer 才能"暂停并恢复"

config = {"configurable": {"thread_id": "case-1"}}

print("\n== B. 人机协同 ==")
# 第一次调用：走到 interrupt 会"暂停"。注意本项目锁定 langgraph 0.2.62，
# 这个版本 invoke() 不抛异常，而是直接返回；要自己看 get_state().next 判断是否暂停。
app2.invoke({"amount": 80000.0}, config=config)
print("  流程暂停，等待人工…… 下一个待办节点：", app2.get_state(config).next)

# 人工拍板后，用 Command(resume=...) 恢复
out2 = app2.invoke(Command(resume="reject"), config=config)
print("  人工决定：", out2["decision"])
