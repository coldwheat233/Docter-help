"""Admin 业务中台工具（医院内部用）。

不做：注册/登录/权限（生产应由 IdP 提供）
做：CRUD 排班/医生/患者/预约 + 审计日志
"""

from __future__ import annotations

import json
from typing import Any


# =====================================================================
# 排班管理
# =====================================================================
def admin_create_schedule(
    doctor_id: int,
    schedule_date: str,  # YYYY-MM-DD
    time_slot: str,  # morning/afternoon/evening
    capacity: int = 20,
    actor: str = "admin",
) -> dict:
    """创建排班（admin 用）。

    Returns:
        {success, schedule_id, error_message}
    """
    from datetime import date
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import ScheduleRepository, AuditLogRepository

    db = get_db()
    repo = ScheduleRepository(db)
    audit = AuditLogRepository(db)

    try:
        sd = date.fromisoformat(schedule_date)
    except ValueError as e:
        return {"success": False, "error_message": f"日期格式错误：{e}"}

    try:
        sched_id = repo.create(
            doctor_id=doctor_id,
            schedule_date=sd,
            time_slot=time_slot,
            capacity=capacity,
        )
    except Exception as e:
        return {"success": False, "error_message": str(e)}

    # 审计
    audit.write(
        event_type="admin.schedule.create",
        entity_type="schedule",
        entity_id=str(sched_id),
        actor=actor,
        action="create",
        before_state=None,
        after_state={"doctor_id": doctor_id, "schedule_date": schedule_date, "time_slot": time_slot, "capacity": capacity},
        metadata={"source": "admin_panel"},
    )
    db.commit()

    return {"success": True, "schedule_id": sched_id, "doctor_id": doctor_id, "schedule_date": schedule_date}


def admin_cancel_schedule(schedule_id: int, reason: str = "", actor: str = "admin") -> dict:
    """取消排班（医院医生请假等场景）。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import ScheduleRepository, AuditLogRepository

    db = get_db()
    repo = ScheduleRepository(db)
    audit = AuditLogRepository(db)

    before = repo.get_by_id(schedule_id)
    if not before:
        return {"success": False, "error_message": f"schedule {schedule_id} 不存在"}

    try:
        # 改 is_available=False（不删，让历史预约还在）
        new_version = repo.update(
            schedule_id=schedule_id,
            expected_version=before["version"],
            is_available=False,
        )
    except Exception as e:
        return {"success": False, "error_message": str(e)}

    audit.write(
        event_type="admin.schedule.cancel",
        entity_type="schedule",
        entity_id=str(schedule_id),
        actor=actor,
        action="cancel",
        before_state={"is_available": True},
        after_state={"is_available": False, "version": new_version},
        metadata={"reason": reason, "source": "admin_panel"},
    )
    db.commit()

    return {"success": True, "schedule_id": schedule_id, "is_available": False, "reason": reason}


def admin_restore_schedule(schedule_id: int, actor: str = "admin") -> dict:
    """恢复排班（取消请假）。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import ScheduleRepository, AuditLogRepository

    db = get_db()
    repo = ScheduleRepository(db)
    audit = AuditLogRepository(db)

    before = repo.get_by_id(schedule_id)
    if not before:
        return {"success": False, "error_message": f"schedule {schedule_id} 不存在"}

    try:
        new_version = repo.update(
            schedule_id=schedule_id,
            expected_version=before["version"],
            is_available=True,
        )
    except Exception as e:
        return {"success": False, "error_message": str(e)}

    audit.write(
        event_type="admin.schedule.restore",
        entity_type="schedule",
        entity_id=str(schedule_id),
        actor=actor,
        action="restore",
        before_state={"is_available": False},
        after_state={"is_available": True, "version": new_version},
        metadata={"source": "admin_panel"},
    )
    db.commit()

    return {"success": True, "schedule_id": schedule_id, "is_available": True}


def admin_adjust_capacity(schedule_id: int, new_capacity: int, actor: str = "admin") -> dict:
    """调整号源（加号 / 减号）。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import ScheduleRepository, AuditLogRepository

    db = get_db()
    repo = ScheduleRepository(db)
    audit = AuditLogRepository(db)

    before = repo.get_by_id(schedule_id)
    if not before:
        return {"success": False, "error_message": f"schedule {schedule_id} 不存在"}

    if new_capacity < before["remaining"]:
        return {
            "success": False,
            "error_message": (
                f"新容量 {new_capacity} 小于已预约数 {before['remaining']}，"
                f"请先取消部分预约"
            ),
        }

    try:
        new_version = repo.update(
            schedule_id=schedule_id,
            expected_version=before["version"],
            capacity=new_capacity,
        )
    except Exception as e:
        return {"success": False, "error_message": str(e)}

    audit.write(
        event_type="admin.schedule.adjust_capacity",
        entity_type="schedule",
        entity_id=str(schedule_id),
        actor=actor,
        action="update",
        before_state={"capacity": before["capacity"]},
        after_state={"capacity": new_capacity, "version": new_version},
        metadata={"source": "admin_panel"},
    )
    db.commit()

    return {
        "success": True,
        "schedule_id": schedule_id,
        "old_capacity": before["capacity"],
        "new_capacity": new_capacity,
    }


# =====================================================================
# 医生管理
# =====================================================================
def admin_create_doctor(
    name: str,
    department: str,
    title: str = "主治医师",
    specialty: str = "",
    actor: str = "admin",
) -> dict:
    """创建医生。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DoctorRepository, DepartmentRepository, AuditLogRepository

    db = get_db()
    # 验证科室存在
    if not DepartmentRepository(db).get_by_name(department):
        return {"success": False, "error_message": f"科室 {department} 不存在"}

    repo = DoctorRepository(db)
    audit = AuditLogRepository(db)

    try:
        doc_id = repo.create(
            name=name, department=department, title=title, specialty=specialty
        )
    except Exception as e:
        return {"success": False, "error_message": str(e)}

    audit.write(
        event_type="admin.doctor.create",
        entity_type="doctor",
        entity_id=str(doc_id),
        actor=actor,
        action="create",
        before_state=None,
        after_state={"name": name, "department": department, "title": title},
        metadata={"source": "admin_panel"},
    )
    db.commit()

    return {"success": True, "doctor_id": doc_id, "name": name}


# =====================================================================
# 预约管理
# =====================================================================
def admin_cancel_appointment(appointment_id: str, reason: str = "", actor: str = "admin") -> dict:
    """管理员强制取消预约（医院主动取消时用）。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import AppointmentRepository, AuditLogRepository

    db = get_db()
    repo = AppointmentRepository(db)
    audit = AuditLogRepository(db)

    before = repo.get_by_id(appointment_id)
    if not before:
        return {"success": False, "error_message": f"预约 {appointment_id} 不存在"}

    try:
        repo.update_status(appointment_id, "cancelled", cancelled_reason=reason, actor=actor)
    except Exception as e:
        return {"success": False, "error_message": str(e)}

    after = repo.get_by_id(appointment_id)
    audit.write(
        event_type="admin.appointment.cancel",
        entity_type="appointment",
        entity_id=appointment_id,
        actor=actor,
        action="cancel",
        before_state={"status": before["status"]},
        after_state={"status": after["status"], "cancelled_reason": reason},
        metadata={"source": "admin_panel"},
    )
    db.commit()

    return {"success": True, "appointment_id": appointment_id, "cancelled_reason": reason}


# =====================================================================
# 统计
# =====================================================================
def admin_stats_today() -> dict:
    """今日统计。"""
    from datetime import date
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        ScheduleRepository,
        DoctorRepository,
        PatientRepository,
    )

    db = get_db()
    today = date.today().isoformat()

    appt_repo = AppointmentRepository(db)
    sched_repo = ScheduleRepository(db)

    return {
        "total_appointments": appt_repo.count_total(),
        "confirmed": appt_repo.count_by_status("confirmed"),
        "cancelled": appt_repo.count_by_status("cancelled"),
        "completed": appt_repo.count_by_status("completed"),
        "total_schedules": sched_repo.count_total(),
        "total_doctors": len(DoctorRepository(db).list_all()),
        "total_patients": len(PatientRepository(db).list_all()),
    }


def admin_recent_audit_log(limit: int = 50) -> list[dict]:
    """最近审计日志。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import AuditLogRepository

    db = get_db()
    return AuditLogRepository(db).list_recent(limit=limit)
