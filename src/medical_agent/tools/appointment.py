"""预约相关工具（写操作，落库前必须 HITL + 乐观锁 + 幂等性）。

v2 增强：
- 落库前 re-check（防排班已变）
- idempotency_key 防 Agent 重入
- 错误码标准化（便于 Agent 解释给用户）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from langchain_core.tools import tool

from medical_agent.db.repositories import (
    AppointmentRepository,
    OptimisticLockError,
    ScheduleRepository,
    UpstreamChangeRepository,
)


# =====================================================================
# 错误处理辅助
# =====================================================================
def _error_response(code: str, message: str, **extra) -> str:
    """统一错误返回格式。"""
    return json.dumps(
        {"success": False, "error_code": code, "error_message": message, **extra},
        ensure_ascii=False,
    )


def _success_response(data: dict) -> str:
    """统一成功返回格式。"""
    return json.dumps({"success": True, **data}, ensure_ascii=False)


def _recheck_schedule(schedule_id: int) -> dict:
    """落库前 re-check：再查一次排班（防排班已变）。"""
    from medical_agent.db.database import get_db

    db = get_db()
    schedule = ScheduleRepository(db).get_by_id(schedule_id)
    if schedule is None:
        return {"available": False, "reason": "schedule_not_found"}
    if not schedule["is_available"]:
        return {"available": False, "reason": "schedule_disabled"}
    if schedule["remaining"] < 1:
        return {"available": False, "reason": "no_remaining", "remaining": schedule["remaining"]}
    return {
        "available": True,
        "version": schedule["version"],
        "remaining": schedule["remaining"],
    }


# =====================================================================
# 工具函数
# =====================================================================
@tool
def set_appointment(
    patient_id: str,
    doctor_id: int,
    schedule_id: int,
    expected_schedule_version: int,
    idempotency_key: str = "",
    symptoms: str = "",
    duration: str = "",
    severity: str = "",
) -> str:
    """创建预约（落库）。v2：带乐观锁 + 幂等性 + re-check。

    ⚠️ 这是写操作，必须经过 HITL 人工确认后才能调用！

    Args:
        patient_id: 患者 ID
        doctor_id: 医生 ID
        schedule_id: 排班 ID
        expected_schedule_version: 期望的排班版本号（v2 必须传；与 check_availability 返回的 schedule_version 配合）
        idempotency_key: 幂等键（v2 推荐；Agent 重入保护）
        symptoms: 主诉
        duration: 病程
        severity: 严重程度

    Returns:
        JSON 字符串。成功：{"success": true, "appointment_id": ...}
                       失败：{"success": false, "error_code": "OPTIMISTIC_LOCK", ...}
    """
    # 1. 落库前 re-check（防 HITL 审批中排班变了）
    recheck = _recheck_schedule(schedule_id)
    if not recheck["available"]:
        return _error_response(
            "RECHECK_FAILED",
            f"排班 {schedule_id} 当前不可预约：{recheck['reason']}",
            reason=recheck["reason"],
        )

    # 2. 检查上游是否有未应用的变更（如果有时强制 re-fetch）
    from medical_agent.db.database import get_db

    db = get_db()
    upstream = UpstreamChangeRepository(db)
    if upstream.has_pending_change("schedule", str(schedule_id)):
        # 有未处理的变更，强制 Agent 重新查
        return _error_response(
            "UPSTREAM_CHANGED",
            f"排班 {schedule_id} 有上游变更未应用，请重新调用 check_availability",
            pending_changes=upstream.list_pending_for_entity("schedule", str(schedule_id)),
        )

    # 3. 生成 idempotency_key（如果调用方没传）
    effective_key = idempotency_key or f"appt-{uuid.uuid4().hex}"

    # 4. 调 Repository（事务 + 乐观锁 + 幂等性都在里面）
    try:
        appointment_id = AppointmentRepository(db).create(
            patient_id=patient_id,
            doctor_id=doctor_id,
            schedule_id=schedule_id,
            expected_schedule_version=expected_schedule_version,
            symptoms=symptoms,
            duration=duration,
            severity=severity,
            idempotency_key=effective_key,
        )
    except OptimisticLockError as e:
        return _error_response("OPTIMISTIC_LOCK", str(e))

    # 5. 通知下游（mock：打印日志）
    from medical_agent.downstream.notifier import notify_appointment_created
    notify_appointment_created(appointment_id)

    return _success_response(
        {
            "appointment_id": appointment_id,
            "status": "confirmed",
            "created_at": datetime.now().isoformat(),
            "idempotency_key": effective_key,
        }
    )


@tool
def cancel_appointment(appointment_id: str, reason: str = "") -> str:
    """取消预约。v2：状态机校验 + 退号源 + 审计。

    Args:
        appointment_id: 预约单号
        reason: 取消原因

    Returns:
        JSON 字符串
    """
    from medical_agent.db.database import get_db

    db = get_db()
    try:
        AppointmentRepository(db).update_status(
            appointment_id, "cancelled", cancelled_reason=reason, actor="patient"
        )
    except Exception as e:
        return _error_response("CANCEL_FAILED", str(e))

    from medical_agent.downstream.notifier import notify_appointment_cancelled
    notify_appointment_cancelled(appointment_id, reason)

    return _success_response(
        {
            "appointment_id": appointment_id,
            "status": "cancelled",
            "cancelled_at": datetime.now().isoformat(),
        }
    )


@tool
def reschedule_appointment(
    appointment_id: str,
    new_schedule_id: int,
    new_expected_schedule_version: int,
) -> str:
    """改约到新时段。v2：旧 schedule 退号 + 新 schedule 扣号（带乐观锁）。

    Args:
        appointment_id: 预约单号
        new_schedule_id: 新排班 ID
        new_expected_schedule_version: 新排班的期望版本号

    Returns:
        JSON 字符串
    """
    from medical_agent.db.database import get_db

    db = get_db()
    try:
        AppointmentRepository(db).update_schedule(
            appointment_id=appointment_id,
            new_schedule_id=new_schedule_id,
            actor="patient",
        )
    except OptimisticLockError as e:
        return _error_response("OPTIMISTIC_LOCK", str(e))

    from medical_agent.downstream.notifier import notify_appointment_rescheduled
    notify_appointment_rescheduled(appointment_id, new_schedule_id)

    return _success_response(
        {
            "appointment_id": appointment_id,
            "new_schedule_id": new_schedule_id,
            "status": "confirmed",
            "rescheduled_at": datetime.now().isoformat(),
        }
    )


@tool
def restore_appointment(appointment_id: str) -> str:
    """恢复已取消的预约（v2 新增）。限制：取消时间在 24h 内。"""
    from medical_agent.db.database import get_db

    db = get_db()
    try:
        success = AppointmentRepository(db).restore(appointment_id, actor="patient")
    except Exception as e:
        return _error_response("RESTORE_FAILED", str(e))

    if not success:
        return _error_response(
            "RESTORE_NOT_ALLOWED",
            f"预约 {appointment_id} 不满足恢复条件（可能超过 24h 或排班已满）",
        )

    return _success_response(
        {
            "appointment_id": appointment_id,
            "status": "confirmed",
            "restored_at": datetime.now().isoformat(),
        }
    )


def all_appointment_tools() -> list:
    """返回所有预约写操作工具，供 confirmer_agent 注入。"""
    return [
        set_appointment,
        cancel_appointment,
        reschedule_appointment,
        restore_appointment,
    ]
