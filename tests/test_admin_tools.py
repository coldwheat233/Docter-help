"""Admin 业务中台测试。"""

import pytest
from datetime import date, timedelta


@pytest.fixture
def admin_env(temp_db_path):
    """Admin 测试环境：建一个科室 + 医生 + 排班 + 预约。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
        AppointmentRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    DepartmentRepository(db).create(code="GI", name="消化科", description="")
    doc_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    PatientRepository(db).upsert(patient_id="P001", name="测试患者", phone="13800000001")

    sched_id = ScheduleRepository(db).create(
        doctor_id=doc_id,
        schedule_date=date.today() + timedelta(days=1),
        time_slot="morning",
        capacity=10,
    )
    appt_id = AppointmentRepository(db).create(
        patient_id="P001", doctor_id=doc_id, schedule_id=sched_id
    )

    return {
        "doctor_id": doc_id,
        "sched_id": sched_id,
        "appt_id": appt_id,
    }


# =====================================================================
# 排班管理
# =====================================================================
def test_admin_create_schedule(admin_env):
    """创建排班。"""
    from medical_agent.admin_tools import admin_create_schedule

    result = admin_create_schedule(
        doctor_id=admin_env["doctor_id"],
        schedule_date=(date.today() + timedelta(days=2)).isoformat(),
        time_slot="afternoon",
        capacity=15,
    )
    assert result["success"] is True
    assert "schedule_id" in result


def test_admin_create_schedule_invalid_date():
    """日期格式错。"""
    from medical_agent.admin_tools import admin_create_schedule

    result = admin_create_schedule(
        doctor_id=1,
        schedule_date="not-a-date",
        time_slot="morning",
    )
    assert result["success"] is False


def test_admin_cancel_schedule(admin_env):
    """取消排班（医生请假）。"""
    from medical_agent.admin_tools import admin_cancel_schedule

    result = admin_cancel_schedule(admin_env["sched_id"], reason="医生请假")
    assert result["success"] is True
    assert result["is_available"] is False


def test_admin_cancel_schedule_not_found(temp_db_path):
    """schedule 不存在。"""
    from medical_agent.admin_tools import admin_cancel_schedule

    result = admin_cancel_schedule(99999)
    assert result["success"] is False
    assert "不存在" in result["error_message"]


def test_admin_restore_schedule(admin_env):
    """恢复排班。"""
    from medical_agent.admin_tools import admin_cancel_schedule, admin_restore_schedule

    # 先取消
    admin_cancel_schedule(admin_env["sched_id"])
    # 再恢复
    result = admin_restore_schedule(admin_env["sched_id"])
    assert result["success"] is True
    assert result["is_available"] is True


def test_admin_adjust_capacity(admin_env):
    """加号（容量增加）。"""
    from medical_agent.admin_tools import admin_adjust_capacity

    result = admin_adjust_capacity(admin_env["sched_id"], new_capacity=20)
    assert result["success"] is True
    assert result["new_capacity"] == 20
    assert result["old_capacity"] == 10


def test_admin_adjust_capacity_too_small(admin_env):
    """新容量 < 已预约数 → 拒绝。"""
    from medical_agent.admin_tools import admin_adjust_capacity

    # remaining=10, 试降到 5 → 拒绝
    result = admin_adjust_capacity(admin_env["sched_id"], new_capacity=5)
    assert result["success"] is False
    assert "新容量" in result["error_message"]


# =====================================================================
# 医生管理
# =====================================================================
def test_admin_create_doctor_success(admin_env):
    """创建医生。"""
    from medical_agent.admin_tools import admin_create_doctor

    result = admin_create_doctor(
        name="李医生",
        department="心内科",
        title="副主任医师",
        specialty="冠心病",
    )
    assert result["success"] is True
    assert "doctor_id" in result


def test_admin_create_doctor_invalid_department(temp_db_path):
    """科室不存在。"""
    from medical_agent.admin_tools import admin_create_doctor

    result = admin_create_doctor(name="X", department="外星科")
    assert result["success"] is False


# =====================================================================
# 预约管理
# =====================================================================
def test_admin_cancel_appointment(admin_env):
    """管理员强制取消预约。"""
    from medical_agent.admin_tools import admin_cancel_appointment

    result = admin_cancel_appointment(
        admin_env["appt_id"], reason="医生临时停诊"
    )
    assert result["success"] is True


def test_admin_cancel_appointment_not_found(temp_db_path):
    """预约不存在。"""
    from medical_agent.admin_tools import admin_cancel_appointment

    result = admin_cancel_appointment("A99999999")
    assert result["success"] is False


# =====================================================================
# 审计日志
# =====================================================================
def test_admin_operations_write_audit_log(admin_env):
    """所有 admin 操作写审计日志。"""
    from medical_agent.admin_tools import admin_adjust_capacity, admin_recent_audit_log
    from medical_agent.db.database import get_db

    # 做几次操作
    admin_adjust_capacity(admin_env["sched_id"], new_capacity=15)
    admin_adjust_capacity(admin_env["sched_id"], new_capacity=18)

    # 查审计
    logs = admin_recent_audit_log(limit=10)
    adjust_logs = [l for l in logs if "adjust_capacity" in l["event_type"]]
    assert len(adjust_logs) >= 2
    # 含 actor
    assert all(l["actor"] == "admin" for l in adjust_logs)


# =====================================================================
# 统计
# =====================================================================
def test_admin_stats(admin_env):
    """今日统计。"""
    from medical_agent.admin_tools import admin_stats_today

    stats = admin_stats_today()
    assert "total_appointments" in stats
    assert "confirmed" in stats
    assert "total_schedules" in stats
    assert "total_doctors" in stats
    assert stats["total_appointments"] >= 1  # admin_env 至少建了 1 个
