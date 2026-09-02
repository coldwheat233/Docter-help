"""Demo 05: 真实业务端到端 demo（5 步流程）。

跑法：python -m demos.05_real_business_demo
或：  PYTHONPATH=src python demos/05_real_business_demo.py

需要：.env 里 DEEPSEEK_API_KEY 真实 key，MOCK_LLM=false

流程（5 步，对应 5 分钟 demo 录屏）：
  1. 用户问候 → router 识别
  2. 用户说想挂号 → intake 追问严重程度
  3. 用户回答中等 → intake 收集完，转 scheduler
  4. scheduler 推荐 3-5 个时段
  5. 用户选时段 → confirmer 复述 + 调 set_appointment 落库

输出：每步打印用户/Agent 对话，可直接复制到实习报告
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from medical_agent.config import get_settings  # noqa: E402
from medical_agent.graphs.supervisor import build_supervisor_app  # noqa: E402


def print_header(title: str) -> None:
    """打印节标题。"""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_turn(turn: int, user_input: str, ai_response: str, duration_ms: int) -> None:
    """打印一轮对话。"""
    print()
    print(f"【轮次 {turn}】")
    print(f"👤 患者：{user_input}")
    print(f"🤖 助手：{ai_response[:500]}")
    print(f"⏱️  耗时：{duration_ms}ms")


def extract_last_ai_content(messages: list) -> str:
    """从 messages 中提取最后一条 AI 消息。"""
    for m in reversed(messages):
        if isinstance(m, AIMessage):
            content = m.content
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                return "".join(c for c in content if isinstance(c, str))
    return "(无 AI 响应)"


def main() -> int:
    settings = get_settings()
    if settings.mock_llm:
        print("⚠️  当前 MOCK_LLM=true，请改 .env 设 MOCK_LLM=false")
        return 1

    if not settings.deepseek_api_key or settings.deepseek_api_key.startswith("sk-mock"):
        print("⚠️  DEEPSEEK_API_KEY 未填或仍是 mock，请改 .env")
        return 1

    print_header("Demo 05: 真实业务端到端（DeepSeek）")
    print(f"Model:    {settings.deepseek_model}")
    print(f"Database: {settings.db_path}")
    print(f"Mock:     {settings.mock_llm}")

    # 1. 构造 Supervisor
    print("\n[1/6] 启动 Supervisor...")
    app = build_supervisor_app()
    config = {"configurable": {"thread_id": "demo-05-real-001"}}
    print("    ✓ 4 子 Agent + Supervisor + Knowledge Agent 已加载")

    # 5 步标准流程
    scenarios = [
        ("问候", "你好"),
        ("挂号意图", "我想挂号，最近一周一直胃疼，吃完饭更严重"),
        ("问诊回答（严重程度）", "中等严重程度吧，影响睡眠"),
        ("指定科室+时段", "消化科，明天上午最好"),
        ("确认预约", "是的，请帮我预约明早 8 点那个"),
    ]

    print(f"\n[2/6] 开始 5 步流程（每步 ~30s）...")
    total_start = time.time()
    for i, (label, query) in enumerate(scenarios, 1):
        start = time.time()
        try:
            result = app.invoke(
                {"messages": [HumanMessage(content=query)]},
                config=config,
            )
            ai_content = extract_last_ai_content(result["messages"])
            duration_ms = int((time.time() - start) * 1000)
            print_turn(i, query, ai_content, duration_ms)
        except Exception as e:
            print(f"    ❌ 轮次 {i} 出错：{type(e).__name__}: {e}")
            return 1

    total_duration = int((time.time() - total_start) * 1000)

    # 总结
    print_header("Demo 总结")
    print(f"总耗时：{total_duration}ms（{total_duration/1000:.1f}s）")
    print(f"轮次：{len(scenarios)}")
    print(f"状态：链路连通，5 步业务流跑通")

    # 查 DB 看看有没有落库
    print(f"\n[3/6] 检查数据库...")
    try:
        from medical_agent.db.database import get_db
        from medical_agent.db.repositories import AppointmentRepository

        db = get_db()
        repo = AppointmentRepository(db)
        total_appts = repo.count_total()
        confirmed = repo.count_by_status("confirmed")
        print(f"    appointments 总数：{total_appts}")
        print(f"    confirmed 状态数：{confirmed}")
    except Exception as e:
        print(f"    DB 检查失败：{e}")

    print()
    print("=" * 70)
    print("Demo 05 完成 ✅")
    print("=" * 70)
    print()
    print("接下来可以做的：")
    print("1. python -m medical_agent.eval.runner --with-app  # 用真 LLM 跑 20 用例")
    print("2. 访问 http://localhost:8501 看 Web UI 效果")
    print("3. 复制本输出到 docs/06-实习报告素材.md")

    return 0


if __name__ == "__main__":
    sys.exit(main())
