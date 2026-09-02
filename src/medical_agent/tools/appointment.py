"""预约相关工具（写操作，落库前必须 HITL + 乐观锁 + 幂等性）。

v3 增强：
- set_appointment 从 state 自动拿参数（LLM 调 set_appointment() 即可）
- 落库前 re-check（防排班已变）
- idempotency_key 防 Agent 重入
- 错误码标准化（便于 Agent 解释给用户）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

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


def _get_state_from_runtime(runtime) -> dict:
    """从 LangGraph runtime 拿 state。"""
    if runtime is None:
        return {}
    try:
        return runtime.state or {}
    except Exception:
        return {}


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
    patient_id: str = "",
    doctor_id: int = 0,
    schedule_id: int = 0,
    expected_schedule_version: int = 0,
    idempotency_key: str = "",
    symptoms: str = "",
    duration: str = "",
    severity: str = "",
    runtime: Any = None,
) -> str:
    """创建预约（落库）。自动从 state 提取 patient_id/doctor_id/schedule_id。

    ⚠️ 这是写操作，必须经过 HITL 人工确认后才能调用！

    调用方式：
    - LLM 调：set_appointment() 即可（自动从 state 拿参数）
    - 显式调：set_appointment(patient_id="P001", doctor_id=1, schedule_id=51, ...)

    自动从 state 提取：
    - patient_id: state["patient_id"]
    - doctor_id:  state["selected_slot"]["doctor_id"]
    - schedule_id: state["selected_slot"]["schedule_id"]
    - expected_schedule_version: state["selected_slot"]["schedule_version"]
    - symptoms/duration/severity: state["symptoms"]/["duration"]/["severity"]

    Returns:
        JSON 字符串。成功：{"success": true, "appointment_id": ...}
                       失败：{"success": false, "error_code": "OPTIMISTIC_LOCK", ...}
    """
    # 1. 从 runtime 拿 state（覆盖默认参数）
    state = _get_state_from_runtime(runtime)
    if not patient_id:
        patient_id = state.get("patient_id", "")
    if not schedule_id:
        schedule_id = state.get("selected_slot", {}).get("schedule_id", 0) if state.get("selected_slot") else 0
    if not doctor_id:
        doctor_id = state.get("selected_slot", {}).get("doctor_id", 0) if state.get("selected_slot") else 0
    if not expected_schedule_version:
        expected_schedule_version = (
            state.get("selected_slot", {}).get("schedule_version", 0) if state.get("selected_slot") else 0
        )
    if not symptoms:
        symptoms = state.get("symptoms", "")
    if not duration:
        duration = state.get("duration", "")
    if not severity:
        severity = state.get("severity", "")

    # 2. 校验必填
    if not patient_id or not schedule_id or not doctor_id:
        return _error_response(
            "MISSING_PARAMS",
            f"必填参数缺失：patient_id={patient_id}, doctor_id={doctor_id}, schedule_id={schedule_id}",
            hint="LLM 调 set_appointment() 时应从 state 提取；或显式传参",
        )

    # 3. 落库前 re-check（防 HITL 审批中排班变了）
    recheck = _recheck_schedule(schedule_id)
    if not recheck["available"]:
        return _error_response(
            "RECHECK_FAILED",
            f"排班 {schedule_id} 当前不可预约：{recheck['reason']}",
            reason=recheck["reason"],
        )

    # 4. 检查上游是否有未应用的变更
    from medical_agent.db.database import get_db

    db = get_db()
    upstream = UpstreamChangeRepository(db)
    if upstream.has_pending_change("schedule", str(schedule_id)):
        return _error_response(
            "UPSTREAM_CHANGED",
            f"排班 {schedule_id} 有上游变更未应用，请重新调用 check_availability",
        )

    # 5. 生成 idempotency_key
    effective_key = idempotency_key or f"appt-{uuid.uuid4().hex}"

    # 6. 调 Repository
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

    # 7. 通知下游
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
