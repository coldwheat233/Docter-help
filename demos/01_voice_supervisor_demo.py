"""Demo 01: Supervisor 基础演示。

目标：验证 langgraph-supervisor 包能正常工作，跑通最小可运行 Supervisor。
场景：模拟一个"客服分流"——2 个 Agent + Supervisor 路由。

第 1 周产出物：能跑通即说明 supervisor 包安装正确。
"""

import sys
from pathlib import Path

# 把 src 加到 path（demo 独立运行时不依赖包安装）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.prebuilt import create_react_agent  # noqa: E402
from langgraph_supervisor import create_supervisor  # noqa: E402

from medical_agent.llm import get_llm  # noqa: E402


def build_minimal_supervisor():
    """构造最小 Supervisor：售前 Agent + 售后 Agent + Supervisor。"""
    llm = get_llm()

    # 子 Agent 1：售前（处理咨询）
    sales_agent = create_react_agent(
        model=llm,
        tools=[],
        name="sales_expert",
        prompt=(
            "你是售前客服，专门回答产品咨询问题。"
            "如果用户问的是售后问题（退款、维修），调用 transfer_to_after_sales 工具转交售后。"
        ),
    )

    # 子 Agent 2：售后（处理退款、维修）
    after_sales_agent = create_react_agent(
        model=llm,
        tools=[],
        name="after_sales_expert",
        prompt=(
            "你是售后客服，专门处理退款和维修请求。"
            "如果用户问的是售前问题（产品功能、价格），调用 transfer_to_sales 工具转交售前。"
        ),
    )

    # Supervisor
    workflow = create_supervisor(
        agents=[sales_agent, after_sales_agent],
        model=llm,
        prompt=(
            "你是客服调度中心。\n"
            "- 售前/产品/价格类问题 → sales_expert\n"
            "- 售后/退款/维修类问题 → after_sales_expert"
        ),
        output_mode="last_message",
        add_handoff_messages=True,
        supervisor_name="supervisor",
    )

    return workflow.compile(checkpointer=InMemorySaver())


def main():
    print("=" * 60)
    print("Demo 01: Supervisor 基础演示")
    print("=" * 60)
    print("场景：客服分流（售前 vs 售后）")
    print()

    app = build_minimal_supervisor()
    config = {"configurable": {"thread_id": "demo-01-001"}}

    # 测试 3 条 query
    queries = [
        "你们的产品多少钱？",  # → sales_expert
        "我想申请退款",  # → after_sales_expert
        "血压计坏了能修吗？",  # → after_sales_expert
    ]

    for i, q in enumerate(queries, 1):
        print(f"\n[{i}] 👤 用户：{q}")
        try:
            result = app.invoke(
                {"messages": [HumanMessage(content=q)]},
                config=config,
            )
            # 显示最后一条 assistant 消息
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
    print("✓ Demo 01 跑通：langgraph-supervisor 包工作正常")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
