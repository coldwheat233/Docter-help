"""预约查询工具：给 Agent + Web UI 用。

- query_my_appointments：查当前 patient_id 的所有预约
- get_appointment_detail：查单条预约详情
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


def _get_state_from_runtime(runtime) -> dict:
    """从 LangGraph runtime 拿 state。"""
    if runtime is None:
        return {}
    try:
        return runtime.state or {}
    except Exception:
        return {}


@tool
def query_my_appointments(
    status: str = "",
    limit: int = 10,
    runtime: Any = None,
) -> str:
    """查询当前患者的预约列表（含历史记录，按即将就诊在前排序）。

    Args:
        status: 过滤状态（pending/confirmed/cancelled/completed/no_show），空=全部
        limit: 返回条数（默认 10）
        runtime: LangGraph runtime（自动注入）

    Returns:
        JSON 字符串：{patient_id, upcoming_count, history_count, appointments: [...]}
        每条含 is_upcoming/is_past 标记与就诊日期、时段、医生、科室
    """
    from datetime import datetime

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DoctorRepository,
        ScheduleRepository,
    )
    from medical_agent.progress import emit_progress

    emit_progress("🔍 正在查询您的预约记录…")

    # 1. 从 runtime 拿 patient_id
    state = _get_state_from_runtime(runtime)
    patient_id = state.get("patient_id", "")

    if not patient_id:
        return json.dumps(
            {
                "success": False,
                "error_code": "NO_PATIENT_ID",
                "error_message": "无法识别当前患者（请先登录）",
                "appointments": [],
            },
            ensure_ascii=False,
        )

    # 2. 查 DB
    db = get_db()
    repo = AppointmentRepository(db)
    schedule_repo = ScheduleRepository(db)
    doctor_repo = DoctorRepository(db)

    try:
        appts = repo.list_by_patient(patient_id, status=status or None)
    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "error_code": "DB_ERROR",
                "error_message": str(e),
            },
            ensure_ascii=False,
        )

    # 3. 整理：联查排班/医生，算 is_past / is_upcoming
    now = datetime.now()
    today_iso = now.date().isoformat()
    hhmm = now.strftime("%H:%M")

    def _is_past(sched: dict | None) -> bool:
        """排班时间已过（昨天的号，或今天但 end_time 已到）。"""
        if not sched:
            return False
        d = str(sched.get("schedule_date", ""))
        if d and d < today_iso:
            return True
        if d == today_iso:
            end = str(sched.get("end_time", ""))[:5]
            if end and end <= hhmm:
                return True
        return False

    upcoming: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for a in appts[: 4 * limit]:  # 上限保护，避免全表联查
        sched = schedule_repo.get_by_id(a["schedule_id"])
        doctor = doctor_repo.get_by_id(a["doctor_id"]) or {}
        past = _is_past(sched)
        is_upcoming = (not past) and a["status"] in ("pending", "confirmed")
        item = {
            "appointment_id": a["id"],
            "status": a["status"],
            "is_upcoming": is_upcoming,
            "is_past": past,
            "schedule_date": (sched or {}).get("schedule_date", ""),
            "time_slot": (sched or {}).get("time_slot", ""),
            "start_time": str((sched or {}).get("start_time", ""))[:5],
            "end_time": str((sched or {}).get("end_time", ""))[:5],
            "doctor_name": doctor.get("name", ""),
            "doctor_title": doctor.get("title", ""),
            "department": doctor.get("department", ""),
            "symptoms": a.get("symptoms", ""),
            "created_at": a.get("created_at", ""),
            "confirmed_at": a.get("confirmed_at", ""),
            "cancelled_at": a.get("cancelled_at", ""),
            "cancelled_reason": a.get("cancelled_reason", ""),
            # 内部字段：改约/取消流程要用
            "doctor_id": a["doctor_id"],
            "schedule_id": a["schedule_id"],
        }
        (upcoming if is_upcoming else history).append(item)

    # 即将就诊按时间正排（最近的在最上），历史按时间倒排（最近的过去在前）
    upcoming.sort(key=lambda x: (x["schedule_date"], x["start_time"]))
    history.sort(key=lambda x: (x["schedule_date"], x["created_at"]), reverse=True)
    items = (upcoming + history)[:limit]

    return json.dumps(
        {
            "success": True,
            "patient_id": patient_id,
            "upcoming_count": len(upcoming),
            "history_count": len(history),
            "status_filter": status or "all",
            "appointments": items,
        },
        ensure_ascii=False,
    )


@tool
def get_appointment_detail(
    appointment_id: str,
    runtime: Any = None,
) -> str:
    """查询单条预约详情。

    Args:
        appointment_id: 预约号
        runtime: LangGraph runtime

    Returns:
        JSON 字符串：{appointment, doctor, schedule} 或错误
    """
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DoctorRepository,
        ScheduleRepository,
    )

    if not appointment_id:
        return json.dumps(
            {"success": False, "error_code": "MISSING_ID", "error_message": "需要 appointment_id"},
            ensure_ascii=False,
        )

    db = get_db()
    appt_repo = AppointmentRepository(db)
    appt = appt_repo.get_by_id(appointment_id)
    if not appt:
        return json.dumps(
            {"success": False, "error_code": "NOT_FOUND", "error_message": "预约不存在"},
            ensure_ascii=False,
        )

    # 验证权限：当前 patient 只能查自己的
    state = _get_state_from_runtime(runtime)
    current_patient = state.get("patient_id", "")
    if current_patient and appt["patient_id"] != current_patient:
        return json.dumps(
            {
                "success": False,
                "error_code": "FORBIDDEN",
                "error_message": "无权查看此预约",
            },
            ensure_ascii=False,
        )

    # 查医生和排班
    doctor = DoctorRepository(db).get_by_id(appt["doctor_id"])
    schedule = ScheduleRepository(db).get_by_id(appt["schedule_id"])

    return json.dumps(
        {
            "success": True,
            "appointment": {
                "id": appt["id"],
                "status": appt["status"],
                "patient_id": appt["patient_id"],
                "symptoms": appt.get("symptoms", ""),
                "duration": appt.get("duration", ""),
                "severity": appt.get("severity", ""),
                "created_at": appt.get("created_at", ""),
                "confirmed_at": appt.get("confirmed_at", ""),
                "cancelled_at": appt.get("cancelled_at", ""),
                "cancelled_reason": appt.get("cancelled_reason", ""),
            },
            "doctor": (
                {
                    "name": doctor["name"],
                    "title": doctor["title"],
                    "department": doctor["department"],
                }
                if doctor
                else None
            ),
            "schedule": (
                {
                    "schedule_date": schedule["schedule_date"],
                    "time_slot": schedule["time_slot"],
                    "start_time": schedule["start_time"],
                    "end_time": schedule["end_time"],
                }
                if schedule
                else None
            ),
        },
        ensure_ascii=False,
    )


def all_query_tools() -> list:
    """返回所有查询工具。"""
    return [query_my_appointments, get_appointment_detail]
