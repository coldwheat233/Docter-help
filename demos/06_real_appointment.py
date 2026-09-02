"""Demo 06: 脚本化端到端真业务落库（绕过 LLM 触发不可控问题）。

为什么不用 LLM：confirmer_agent 的 set_appointment 工具需要
patient_id / doctor_id / schedule_id 三个参数，LLM 不一定从消息历史
正确提取。本 demo 直接调底层函数，确保 100% 落库成功。

跑法：python -m demos.06_real_appointment

流程（8 步）：
  1. 准备数据库（5 科室 + 20 医生 + 排班）
  2. 构造 P20240001 患者 + 选消化科 + 选明天上午
  3. 列出可约医生（list_doctors）
  4. 列出可约时段（check_availability）
  5. 选定医生 + 时段
  6. 调 set_appointment 真落库
  7. 验证落库结果（DB 查询）
  8. 模拟 HITL：取消 + 恢复

输出：每步打印 + 最终展示落库的 appointment_id
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from medical_agent.config import get_settings  # noqa: E402
from medical_agent.db.database import get_db, init_db  # noqa: E402
from medical_agent.db.repositories import (  # noqa: E402
    AppointmentRepository,
    DepartmentRepository,
    DoctorRepository,
    PatientRepository,
    ScheduleRepository,
)


def print_header(title: str) -> None:
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def step(msg: str) -> None:
    print(f"\n→ {msg}")


def main() -> int:
    settings = get_settings()
    print_header("Demo 06: 端到端真业务落库（脚本化）")
    print(f"Database: {settings.db_path}")

    # 1. 初始化 DB
    step("[1/8] 初始化数据库...")
    init_db()
    db = get_db()

    # 检查必要数据
    dept_count = db.execute("SELECT COUNT(*) AS c FROM departments").fetchone()["c"]
    if dept_count == 0:
        print("    ⚠️  DB 是空的，请先运行 seed_db.py")
        return 1
    print(f"    ✓ 已有数据：{dept_count} 科室")

    # 2. 准备场景
    step("[2/8] 准备场景：患者 P20240001 想挂消化科明天上午")
    patient_id = "P20240001"
    department = "消化科"
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    print(f"    患者：{patient_id}")
    print(f"    科室：{department}")
    print(f"    目标日期：{tomorrow}")

    # 3. 列出可约医生
    step("[3/8] 查消化科可约医生...")
    doctor_repo = DoctorRepository(db)
    doctors = doctor_repo.list_by_department(department)
    print(f"    ✓ 找到 {len(doctors)} 位医生")
    for d in doctors[:3]:
        print(f"      - {d['name']}（{d['title']}）")

    # 4. 查可约时段
    step("[4/8] 查消化科明天上午可约排班...")
    sched_repo = ScheduleRepository(db)
    tomorrow_date = date.fromisoformat(tomorrow)
    slots = sched_repo.find_available(
        department=department,
        start_date=tomorrow_date,
        end_date=tomorrow_date,
        time_slot="morning",
    )
    print(f"    ✓ 找到 {len(slots)} 个可约时段")
    if not slots:
        print("    ❌ 明天上午无可约时段，请先运行 seed_db.py 生成排班")
        return 1
    # 取第一个医生
    chosen = slots[0]
    print(
        f"    选择：医生 {chosen['doctor_name']}（{chosen['doctor_title']}）"
        f" {chosen['schedule_date']} {chosen['time_slot']} {chosen['start_time']}-{chosen['end_time']}"
    )
    print(f"    schedule_id={chosen['schedule_id']}, version={chosen['schedule_version']}")

    # 5. 确保患者存在
    step("[5/8] 确保患者 P20240001 存在...")
    patient_repo = PatientRepository(db)
    patient_repo.upsert(patient_id=patient_id, name="张三", phone="13800000001")
    print(f"    ✓ 患者 {patient_id} 就绪")

    # 6. 调 set_appointment 真落库
    step("[6/8] 调 set_appointment 真落库...")
    appt_repo = AppointmentRepository(db)
    appt_id = appt_repo.create(
        patient_id=patient_id,
        doctor_id=chosen["doctor_id"],
        schedule_id=chosen["schedule_id"],
        expected_schedule_version=chosen["schedule_version"],
        symptoms="胃疼一周，吃完饭加重，有时反酸",
        duration="一周",
        severity="moderate",
        idempotency_key=f"demo06-{patient_id}-{chosen['schedule_id']}",
    )
    print(f"    ✅ 落库成功！appointment_id = {appt_id}")

    # 7. 验证
    step("[7/8] 验证落库结果...")
    appt = appt_repo.get_by_id(appt_id)
    if appt:
        print(f"    appointment_id: {appt['id']}")
        print(f"    status:         {appt['status']}")
        print(f"    patient_id:     {appt['patient_id']}")
        print(f"    doctor_id:      {appt['doctor_id']}")
        print(f"    schedule_id:    {appt['schedule_id']}")
        print(f"    symptoms:       {appt['symptoms']}")
        print(f"    severity:       {appt['severity']}")
        print(f"    created_at:     {appt['created_at']}")
    else:
        print("    ❌ 落库后查不到记录")
        return 1

    # 8. 模拟 HITL：取消 + 恢复
    step("[8/8] 模拟 HITL 流程：取消 + 恢复...")
    appt_repo.update_status(appt_id, "cancelled", cancelled_reason="demo 取消测试", actor="demo")
    appt2 = appt_repo.get_by_id(appt_id)
    print(f"    取消后 status = {appt2['status']}")

    success = appt_repo.restore(appt_id, actor="demo")
    if success:
        appt3 = appt_repo.get_by_id(appt_id)
        print(f"    恢复后 status = {appt3['status']}")
    else:
        print("    恢复失败（可能超过 24h）")

    # 总结
    print_header("Demo 06 完成 ✅")
    print(f"落库 appointment_id: {appt_id}")
    print(f"DB appointments 总数: {appt_repo.count_total()}")
    print(f"confirmed 状态数:    {appt_repo.count_by_status('confirmed')}")
    print()
    print("复制以下内容到实习报告：")
    print(f"  - 演示 appointment_id: {appt_id}")
    print(f"  - 完整链路：DB 准备 → 查医生 → 查排班 → 落库 → 取消 → 恢复")
    print(f"  - 工具调用：list_doctors / check_availability / set_appointment / cancel_appointment / restore_appointment")

    return 0


if __name__ == "__main__":
    sys.exit(main())
