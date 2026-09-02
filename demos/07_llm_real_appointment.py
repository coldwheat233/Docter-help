"""Demo 07: LLM 真触发落库 demo。

策略：脚本预置 state（patient_id + selected_slot），让 LLM 走完 confirmer 流程，
通过 set_appointment() 工具真落库（无需传参，自动从 state 拿）。

跑法：python -m demos.07_llm_real_appointment

为什么 demo 05/06 LLM 没触发：
  - demo 05：confirmer 的 set_appointment 需要从消息历史提取 3 个参数，LLM 识别不准
  - demo 06：完全跳过 LLM，直接调底层

本 demo 修法：
  - 在 supervisor state 里预置 patient_id + selected_slot
  - LLM 走完确认流程后调 set_appointment()（无参）
  - 工具自动从 runtime state 拿参数
  - 落库成功！
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from langchain_core.messages import HumanMessage  # noqa: E402

from medical_agent.config import get_settings  # noqa: E402
from medical_agent.db.database import get_db  # noqa: E402
from medical_agent.db.repositories import (  # noqa: E402
    AppointmentRepository,
    DepartmentRepository,
    DoctorRepository,
    PatientRepository,
    ScheduleRepository,
)
from medical_agent.graphs.supervisor import build_supervisor_app  # noqa: E402


def main() -> int:
    settings = get_settings()
    if settings.mock_llm:
        print("⚠️  请设 MOCK_LLM=false")
        return 1
    if not settings.deepseek_api_key or settings.deepseek_api_key.startswith("sk-mock"):
        print("⚠️  DEEPSEEK_API_KEY 缺失")
        return 1

    print("=" * 70)
    print("  Demo 07: LLM 真触发落库")
    print("=" * 70)

    # 1. 准备 DB（用已有数据，没则创建）
    db = get_db()

    # 检查消化科和医生是否存在
    dept = DepartmentRepository(db).get_by_name("消化科")
    if not dept:
        DepartmentRepository(db).create(code="GI", name="消化科", description="")
        print("\n[1/5] 创建消化科")
    else:
        print(f"\n[1/5] 消化科已存在")

    # 找消化科医生
    doctors = DoctorRepository(db).list_by_department("消化科")
    if doctors:
        # 复用第一个医生
        doctor_id = doctors[0]["id"]
        print(f"      复用医生: {doctors[0]['name']} (id={doctor_id})")
    else:
        doctor_id = DoctorRepository(db).create(name="王医生", department="消化科", title="主任医师")
        print(f"      创建医生: id={doctor_id}")

    # 找或创建排班
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    tomorrow_date = date.fromisoformat(tomorrow)
    slots = ScheduleRepository(db).find_available(
        department="消化科", start_date=tomorrow_date, end_date=tomorrow_date, time_slot="morning"
    )
    if slots:
        sched_id = slots[0]["schedule_id"]
        sched = ScheduleRepository(db).get_by_id(sched_id)
        print(f"      复用排班: id={sched_id} (version={sched['version']})")
    else:
        sched_id = ScheduleRepository(db).create(
            doctor_id=doctor_id, schedule_date=tomorrow_date, time_slot="morning", capacity=10
        )
        sched = ScheduleRepository(db).get_by_id(sched_id)
        print(f"      创建排班: id={sched_id} (version={sched['version']})")

    PatientRepository(db).upsert(patient_id="P20240001", name="张三", phone="13800000001")
    print(f"      患者 P20240001 就绪")

    # 2. 启动 Supervisor
    app = build_supervisor_app()
    print("[2/5] Supervisor + 4 子 Agent + set_appointment(state 感知版) 已加载")

    # 3. 多轮对话，让 LLM 走完收集
    config = {"configurable": {"thread_id": "demo-07-llm-001"}}

    # 把 patient_id 和 selected_slot 写进 state（在 invoke 之前的初始 state）
    initial_state = {
        "messages": [],
        "patient_id": "P20240001",
        "selected_slot": {
            "schedule_id": sched_id,
            "doctor_id": doctor_id,
            "doctor_name": "王医生",
            "doctor_title": "主任医师",
            "department": "消化科",
            "schedule_date": (date.today() + timedelta(days=1)).isoformat(),
            "time_slot": "morning",
            "start_time": "08:00",
            "end_time": "12:00",
            "schedule_version": sched["version"],
        },
        "symptoms": "胃疼一周",
        "duration": "一周",
        "severity": "moderate",
    }

    queries = [
        # 多轮让 LLM 走完收集，再确认
        "请帮我预约 P20240001 消化科明天上午的号",
        "我选第一个医生李文博的 8 点时段",
        "确认",
    ]

    print("\n[3/5] LLM 对话（2 轮）...")
    for q in queries:
        try:
            r = app.invoke(
                {**initial_state, "messages": [HumanMessage(content=q)]},
                config=config,
            )
            last = r["messages"][-1]
            content = last.content if hasattr(last, "content") else str(last)
            print(f"  👤 用户：{q}")
            print(f"  🤖 助手：{str(content)[:300]}")
            # 显示 tool calls
            tool_msgs = [m for m in r["messages"] if type(m).__name__ == "ToolMessage"]
            if tool_msgs:
                print(f"  🔧 工具调用 ({len(tool_msgs)}):")
                for tm in tool_msgs:
                    print(f"      {tm.name}: {tm.content[:150]}")
        except Exception as e:
            print(f"  ❌ 出错：{e}")
            import traceback
            traceback.print_exc()

    # 4. 验证落库
    print("\n[4/5] 验证落库...")
    appt_repo = AppointmentRepository(db)
    total = appt_repo.count_total()
    confirmed = appt_repo.count_by_status("confirmed")
    print(f"  appointments 总数: {total}")
    print(f"  confirmed 状态数: {confirmed}")

    if total > 0:
        appt = appt_repo.list_by_patient("P20240001")[0]
        print(f"\n[5/5] 落库成功！")
        print(f"  appointment_id: {appt['id']}")
        print(f"  status:         {appt['status']}")
        print(f"  schedule_id:    {appt['schedule_id']}")
        return 0
    else:
        print("\n[5/5] ❌ LLM 没触发落库")
        print("    可能原因：")
        print("    1. LLM 没调 set_appointment 工具")
        print("    2. 工具被调但参数缺失")
        print("    3. 工具被调但 state 字段未传")
        return 1


if __name__ == "__main__":
    sys.exit(main())
