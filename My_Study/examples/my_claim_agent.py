"""
Day 7 最终成品：我的简化版理赔 Agent 工作流
============================================
把前六天学到的全部串起来，做一个能跑的理赔审核工作流：

    intake(报案) → policy(查保单) → experts(并行三专家) → route(条件路由)
                                        ├── auto(自动受理)
                                        ├── investigate(风险调查)
                                        └── review(人工审核, interrupt 暂停等人)

运行（在项目根目录）：
    .\\.venv-py314\\Scripts\\python.exe My_Study\\my_claim_agent.py --demo
    ... --demo --amount 80000        # 大额，走人工（演示暂停+恢复）
    ... --demo --scenario risk       # 高风险，走调查
    ... --real                       # 专家意见用 DeepSeek 真实生成（需 .env key）

对照老师项目：这就是 agents/claim_agent.py 里 build_claim_graph 的简化版。
"""

import os
import sys
import json
import operator
import argparse
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import StateGraph, START, END
from langgraph.types import Send, interrupt, Command
from langgraph.checkpoint.memory import MemorySaver


# ---- 状态：流程里流动的数据 ----
class ClaimState(TypedDict, total=False):
    claim_id: str
    description: str
    policy_id: str
    amount: float
    policy_ok: bool
    expert_reports: Annotated[list[dict], operator.add]   # 三专家结果自动合并成列表
    risk_score: float
    decision: str
    message: str


# ---- 各节点 ----
def intake(state: ClaimState) -> dict:
    # 报案：缺保单号就暂停补材料（真实项目这里用 interrupt）
    if not state.get("policy_id"):
        pid = interrupt({"kind": "info", "missing": "policy_id"})
        return {"policy_id": pid}
    return {}


def policy(state: ClaimState) -> dict:
    # 查保单（合成）：以 POL 开头算有效
    return {"policy_ok": str(state.get("policy_id", "")).startswith("POL")}


def _real_expert(role: str, description: str) -> dict:
    """调用 DeepSeek 生成结构化专家意见（需要 .env 里的 key）。"""
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    llm = ChatOpenAI(
        model=os.getenv("DEEPSEEK_FLASH_MODEL", "deepseek-flash"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    prompt = (
        f"你是理赔{role}专家。根据报案描述给出审核意见，只输出 json 对象，字段为："
        f"recommendation(accept/review/reject)、confidence(0~1)、risk_score(0~1)。"
        f"报案描述：{description}"
    )
    try:
        return json.loads(llm.invoke(prompt).content)
    except Exception:
        return {"recommendation": "review", "confidence": 0, "risk_score": 0.5}


def build_expert_subgraph(real: bool, scenario: str):
    """并行三专家子图。"""
    def dispatch(state: ClaimState) -> list[Send]:
        return [Send("expert", {"role": r, "description": state.get("description", "")})
                for r in ("damage", "risk", "liability")]

    def expert(state: dict) -> dict:
        role = state["role"]
        if real:
            opinion = _real_expert(role, state.get("description", ""))
            opinion["expert"] = role
        else:
            opinion = {"expert": role, "recommendation": "accept", "confidence": 0.9, "risk_score": 0.1}
            if scenario == "risk" and role == "risk":
                opinion = {"expert": role, "recommendation": "review", "confidence": 0.4, "risk_score": 0.9}
        return {"expert_reports": [opinion]}

    def aggregate(state: ClaimState) -> dict:
        risk = next((r["risk_score"] for r in state["expert_reports"] if r["expert"] == "risk"), 0)
        return {"risk_score": risk}

    g = StateGraph(ClaimState)
    g.add_node("expert", expert)
    g.add_node("aggregate", aggregate)
    g.add_conditional_edges(START, dispatch, ["expert"])
    g.add_edge("expert", "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()


def route(state: ClaimState) -> str:
    # 业务规则优先：保单无效、大额、高风险、专家不一致 → 相应分支
    if not state.get("policy_ok"):
        return "reject"
    if state.get("amount", 0) > 50000:
        return "review"
    if (state.get("risk_score") or 0) > 0.7:
        return "investigate"
    reports = state.get("expert_reports", [])
    if len(reports) != 3 or any(r.get("recommendation") != "accept" for r in reports):
        return "review"
    return "auto"


def auto(state: ClaimState) -> dict:
    return {"decision": "accept", "message": "满足条件，建议受理（未执行付款）"}


def investigate(state: ClaimState) -> dict:
    return {"decision": "investigate", "message": "风险较高，建议调查核实"}


def reject(state: ClaimState) -> dict:
    return {"decision": "reject", "message": "保单无效，建议拒赔"}


def review(state: ClaimState) -> dict:
    ans = interrupt({"kind": "review", "allowed": ["accept", "reject"]})
    return {"decision": ans, "message": f"人工决定：{ans}"}


def build_graph(real: bool = False, scenario: str = "normal"):
    g = StateGraph(ClaimState)
    g.add_node("intake", intake)
    g.add_node("policy", policy)
    g.add_node("experts", build_expert_subgraph(real, scenario))
    g.add_node("auto", auto)
    g.add_node("investigate", investigate)
    g.add_node("review", review)
    g.add_node("reject", reject)

    g.add_edge(START, "intake")
    g.add_edge("intake", "policy")
    g.add_conditional_edges("policy", lambda s: "experts" if s["policy_ok"] else "reject",
                            {"experts": "experts", "reject": "reject"})
    g.add_conditional_edges("experts", route, {"auto": "auto", "investigate": "investigate", "review": "review"})
    for n in ("auto", "investigate", "review", "reject"):
        g.add_edge(n, END)
    return g.compile(checkpointer=MemorySaver())


def main() -> None:
    parser = argparse.ArgumentParser(description="简化版理赔 Agent 工作流")
    parser.add_argument("--demo", action="store_true", help="纯合成，不调用大模型")
    parser.add_argument("--real", action="store_true", help="专家意见用 DeepSeek 真实生成")
    parser.add_argument("--scenario", choices=["normal", "risk"], default="normal")
    parser.add_argument("--amount", type=float, default=3200.0)
    parser.add_argument("--policy-id", default="POL-2024-001")
    args = parser.parse_args()

    graph = build_graph(real=args.real, scenario=args.scenario)
    config = {"configurable": {"thread_id": "case-1"}}
    state = {"claim_id": "CLM-001", "description": "停车场车辆刮擦",
             "policy_id": args.policy_id, "amount": args.amount}

    result = graph.invoke(state, config=config)
    pending = graph.get_state(config).next   # 空元组 = 跑完；非空 = 停在某个 interrupt 等人
    if pending:
        print("⚠ 流程暂停，等待人工审核…… 待办节点：", pending)
        result = graph.invoke(Command(resume="accept"), config=config)   # 演示：人工拍板 accept 后恢复
    print("最终决策：", result.get("decision"), "|", result.get("message"))


if __name__ == "__main__":
    main()
