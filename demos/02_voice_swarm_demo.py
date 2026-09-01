"""Demo 02: Swarm 基础演示。

目标：验证 langgraph-swarm 包能正常工作，跑通最小可运行 Swarm。
场景：2 个 Agent 通过 handoff 工具互转。

第 1 周产出物：能跑通即说明 swarm 包安装正确。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from langgraph_swarm import create_handoff_tool, create_swarm  # noqa: E402

from medical_agent.llm import get_llm  # noqa: E402


def build_minimal_swarm():
    """构造最小 Swarm：航班 Agent + 酒店 Agent + handoff 互转。"""
    llm = get_llm()

    # handoff 工具
    transfer_to_hotel = create_handoff_tool(
        agent_name="hotel_agent",
        description="把对话转交给酒店预订专员",
    )
    transfer_to_flight = create_handoff_tool(
        agent_name="flight_agent",
        description="把对话转交给机票预订专员",
    )

    flight_agent = create_react_agent(
        model=llm,
        tools=[transfer_to_hotel],
        name="flight_agent",
        prompt="你是机票预订专员。问酒店时用 transfer_to_hotel 工具转交。",
    )
    hotel_agent = create_react_agent(
        model=llm,
        tools=[transfer_to_flight],
        name="hotel_agent",
        prompt="你是酒店预订专员。订机票时用 transfer_to_flight 工具转交。",
    )

    workflow = create_swarm(
        agents=[flight_agent, hotel_agent],
        default_active_agent="flight_agent",  # 入口
    )

    return workflow.compile(checkpointer=InMemorySaver())


def main():
    print("=" * 60)
    print("Demo 02: Swarm 基础演示")
    print("=" * 60)
    print("场景：机票 + 酒店预订（Agent 互转）")
    print()

    app = build_minimal_swarm()
    config = {"configurable": {"thread_id": "demo-02-001"}}

    # 测试 2 轮对话
    queries = [
        "我想订北京到上海的机票",  # flight_agent
        "顺便也帮我订一晚酒店",  # handoff → hotel_agent
    ]

    for i, q in enumerate(queries, 1):
        print(f"\n[{i}] 👤 用户：{q}")
        try:
            result = app.invoke(
                {"messages": [HumanMessage(content=q)]},
                config=config,
            )
            last = result["messages"][-1]
            content = last.content if hasattr(last, "content") else str(last)
            print(f"[{i}] 🤖 助手：{content[:200]}")
        except Exception as e:
            print(f"[{i}] ❌ 出错：{e}")
            import traceback
            traceback.print_exc()
            return False

    print()
    print("=" * 60)
    print("✓ Demo 02 跑通：langgraph-swarm 包工作正常")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
