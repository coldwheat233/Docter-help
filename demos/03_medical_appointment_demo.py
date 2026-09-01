"""Demo 03: 医疗预约端到端 demo。

场景：用户从自然语言描述到完成预约的全流程。
链路：路由 → 问诊 → 时段推荐 → 人工确认 → 落库

这是核心交付物的雏形。第 1 周跑通整条链路，第 2 周填充业务实现。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from langchain_core.messages import HumanMessage  # noqa: E402

from medical_agent.db.seed import seed_all, print_summary  # noqa: E402
from medical_agent.graphs.supervisor import build_supervisor_app  # noqa: E402


def main(skip_seed: bool = False):
    print("=" * 60)
    print("Demo 03: 医疗预约端到端")
    print("=" * 60)
    print("链路：用户自然语言 → 路由 → 问诊 → 推荐 → HITL → 落库")
    print()

    # 1. 初始化数据
    if not skip_seed:
        print("[1/3] 检查/生成模拟数据...")
        stats = seed_all(reset=False)
        print(f"  ✓ 已有数据：科室 {stats['departments']} / 医生 {stats['doctors']} / 排班 {stats['schedules']}")
    else:
        print("[1/3] 跳过数据初始化")

    # 2. 构造 Supervisor
    print("\n[2/3] 构造 Supervisor...")
    app = build_supervisor_app()
    print("  ✓ 4 个子 Agent + Supervisor 已加载")

    # 3. 跑 demo 对话
    print("\n[3/3] 端到端对话测试")
    print("-" * 60)

    # 第 1 轮：用户发起预约
    config = {"configurable": {"thread_id": "demo-03-patient-001"}}
    query1 = "你好，我想挂个号，这两天老是胃疼，吃东西也不消化"
    print(f"\n👤 患者：{query1}")
    try:
        result = app.invoke(
            {"messages": [HumanMessage(content=query1)]},
            config=config,
        )
        for msg in result["messages"][-3:]:
            content = msg.content if hasattr(msg, "content") else str(msg)
            role = msg.__class__.__name__ if hasattr(msg, "__class__") else "msg"
            print(f"  [{role}] {content[:150]}")
    except Exception as e:
        print(f"❌ 链路出错：{e}")
        import traceback
        traceback.print_exc()
        return False

    print()
    print("=" * 60)
    print("✓ Demo 03 跑通：医疗预约链路连通")
    print("=" * 60)
    print()
    print("注意：第 1 周为 stub 阶段，Agent 不会真正调用工具或落库。")
    print("      完整业务实现见第 2 周 Plan。")
    return True


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-seed", action="store_true")
    args = parser.parse_args()
    success = main(skip_seed=args.skip_seed)
    sys.exit(0 if success else 1)
