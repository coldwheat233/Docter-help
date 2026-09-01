"""模拟数据生成脚本。

用法：python scripts/seed_db.py
     或 python -m medical_agent.db.seed

行为：
1. 初始化数据库（执行 schema.sql）
2. 插入 5 科室 + 20 医生 + 30 天 × 3 时段 × 20 医生 = 1800 条排班
3. 插入 10 个示例患者

可重复执行，已存在数据会被清空。
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from medical_agent.config import get_settings
from medical_agent.db.database import get_db, init_db
from medical_agent.db.repositories import (
    DepartmentRepository,
    DoctorRepository,
    PatientRepository,
    ScheduleRepository,
)


# 5 个固定科室
DEPARTMENTS = [
    ("IM", "心内科", "心血管疾病诊疗，含高血压、冠心病、心律失常等"),
    ("GI", "消化科", "胃肠道、肝胆胰疾病诊疗"),
    ("PD", "儿科", "0-14 岁儿童常见病诊疗"),
    ("OR", "骨科", "骨骼、关节、脊柱、运动损伤"),
    ("DM", "皮肤科", "皮肤病、性病、医学美容"),
]

# 20 个医生姓名（常用姓名库）
DOCTOR_NAMES = [
    "王建国", "李文博", "张志远", "刘洋", "陈静",
    "杨晓东", "黄文军", "赵明", "周伟", "吴敏",
    "徐华", "孙丽", "马俊", "朱强", "胡敏",
    "郭伟", "林涛", "何静", "高翔", "罗强",
]

# 职称按比例分配
TITLES = ["主任医师", "副主任医师", "主治医师", "住院医师"]
TITLE_WEIGHTS = [0.15, 0.30, 0.40, 0.15]

# 10 个示例患者
SAMPLE_PATIENTS = [
    ("P20240001", "张三", "13800000001"),
    ("P20240002", "李四", "13800000002"),
    ("P20240003", "王五", "13800000003"),
    ("P20240004", "赵六", "13800000004"),
    ("P20240005", "钱七", "13800000005"),
    ("P20240006", "孙八", "13800000006"),
    ("P20240007", "周九", "13800000007"),
    ("P20240008", "吴十", "13800000008"),
    ("P20240009", "郑十一", "13800000009"),
    ("P20240010", "王十二", "13800000010"),
]


def seed_all(reset: bool = True) -> dict[str, int]:
    """生成全部模拟数据。

    Args:
        reset: 是否先清空（删除已有数据），True 适合演示，False 适合增量

    Returns:
        各表插入数量
    """
    settings = get_settings()
    init_db()

    db = get_db()

    if reset:
        # 按外键依赖逆序清空
        db.execute("DELETE FROM appointments")
        db.execute("DELETE FROM schedules")
        db.execute("DELETE FROM patients")
        db.execute("DELETE FROM doctors")
        db.execute("DELETE FROM departments")
        db.execute("DELETE FROM sqlite_sequence")
        db.commit()

    # 1. 科室
    dept_repo = DepartmentRepository(db)
    for code, name, desc in DEPARTMENTS:
        dept_repo.create(code=code, name=name, description=desc)

    # 2. 医生（每科室 4 个，共 20 个）
    doctor_repo = DoctorRepository(db)
    dept_names = [d[1] for d in DEPARTMENTS]
    for i, name in enumerate(DOCTOR_NAMES):
        dept = dept_names[i % len(dept_names)]
        title = random.choices(TITLES, weights=TITLE_WEIGHTS, k=1)[0]
        specialty = f"擅长{dept}常见疾病诊疗"
        intro = f"{title}，从事{dept}临床工作 10+ 年"
        doctor_repo.create(
            name=name, department=dept, title=title, specialty=specialty, intro=intro
        )

    # 3. 排班（每个医生每天 3 个时段：上午/下午/晚班）
    schedule_repo = ScheduleRepository(db)
    today = date.today()
    days = settings.schedule_days
    time_slots = ["morning", "afternoon", "evening"]

    total_schedules = 0
    for doctor_id in range(1, settings.doctor_count + 1):
        for d_offset in range(days):
            current_date = today + timedelta(days=d_offset)
            # v2: 节假日不排班
            from medical_agent.upstream.holiday import is_workday
            if not is_workday(current_date):
                continue
            for slot in time_slots:
                # 70% 概率排班（模拟医生不是每天都在）
                if random.random() < 0.70:
                    schedule_repo.create(
                        doctor_id=doctor_id,
                        schedule_date=current_date,
                        time_slot=slot,
                        capacity=20,
                    )
                    total_schedules += 1

    # 4. 患者
    patient_repo = PatientRepository(db)
    for pid, pname, phone in SAMPLE_PATIENTS:
        patient_repo.upsert(patient_id=pid, name=pname, phone=phone)

    db.commit()

    return {
        "departments": len(DEPARTMENTS),
        "doctors": len(DOCTOR_NAMES),
        "schedules": total_schedules,
        "patients": len(SAMPLE_PATIENTS),
    }


def print_summary(stats: dict[str, int]) -> None:
    print("=" * 50)
    print("[OK] seed data generated")
    print("=" * 50)
    print(f"  departments: {stats['departments']}")
    print(f"  doctors:     {stats['doctors']}")
    print(f"  schedules:   {stats['schedules']} rows")
    print(f"  patients:    {stats['patients']}")
    print()
    print(f"data written to: data/medical.db")
    print()
    print("next: python demos/03_medical_appointment_demo.py")


if __name__ == "__main__":
    random.seed(42)  # 固定随机种子，可重复执行结果一致
    stats = seed_all(reset=True)
    print_summary(stats)
