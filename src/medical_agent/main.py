"""主入口。

用法：
    python -m medical_agent.main            # 默认：交互式 Supervisor 模式
    python -m medical_agent.main --swarm    # Swarm 对比模式
    python -m medical_agent.main --seed     # 重新生成模拟数据
    python -m medical_agent.main --query "我想挂号"  # 单条 query
"""

from __future__ import annotations

import argparse
import sys

from langchain_core.messages import HumanMessage

from medical_agent.config import get_settings
from medical_agent.graphs.supervisor import build_supervisor_app
from medical_agent.graphs.swarm import build_swarm_app


def run_interactive(mode: str = "supervisor") -> None:
    """交互式对话循环。"""
    if mode == "supervisor":
        app = build_supervisor_app()
        print("=" * 60)
        print("医疗预约系统 (Supervisor 模式)")
        print("输入 quit 退出")
        print("=" * 60)
    else:
        app = build_swarm_app()
        print("=" * 60)
        print("医疗预约系统 (Swarm 对比模式)")
        print("输入 quit 退出")
        print("=" * 60)

    config = {"configurable": {"thread_id": f"interactive-{mode}-001"}}

    while True:
        try:
            user_input = input("\n👤 你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("再见！")
            break
        if not user_input:
            continue

        try:
            result = app.invoke(
                {"messages": [HumanMessage(content=user_input)]},
                config=config,
            )
            # 最后一条消息
            last_msg = result["messages"][-1]
            print(f"\n🤖 助手：{last_msg.content if hasattr(last_msg, 'content') else last_msg}")
        except Exception as e:
            print(f"\n❌ 出错：{e}")
            import traceback

            traceback.print_exc()


def run_single_query(query: str, mode: str = "supervisor") -> None:
    """运行单条 query。"""
    app = build_supervisor_app() if mode == "supervisor" else build_swarm_app()
    config = {"configurable": {"thread_id": f"single-{mode}-001"}}

    result = app.invoke(
        {"messages": [HumanMessage(content=query)]},
        config=config,
    )
    print(f"\n👤 Query: {query}")
    print(f"🤖 Response: {result['messages'][-1].content}")
    print(f"📊 Total messages: {len(result['messages'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="医疗预约系统")
    parser.add_argument("--swarm", action="store_true", help="使用 Swarm 模式（对比）")
    parser.add_argument("--query", type=str, help="单条 query")
    parser.add_argument("--seed", action="store_true", help="重新生成模拟数据")
    args = parser.parse_args()

    if args.seed:
        from medical_agent.db.seed import seed_all, print_summary

        stats = seed_all(reset=True)
        print_summary(stats)
        return

    mode = "swarm" if args.swarm else "supervisor"
    if args.query:
        run_single_query(args.query, mode=mode)
    else:
        run_interactive(mode=mode)


if __name__ == "__main__":
    main()
