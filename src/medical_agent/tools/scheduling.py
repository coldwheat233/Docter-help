"""排班相关工具（只读）。"""

from __future__ import annotations

import json
from datetime import date, timedelta

from langchain_core.tools import tool

from medical_agent.db.repositories import (
    DepartmentRepository,
    DoctorRepository,
    ScheduleRepository,
)
from medical_agent.config import get_settings


@tool
def list_departments() -> str:
    """列出所有可预约的科室。

    Returns:
        JSON 字符串：科室列表，每项含 id / name / description
    """
    from medical_agent.db.database import get_db

    db = get_db()
    repo = DepartmentRepository(db)
    departments = repo.list_all()
    return json.dumps(departments, ensure_ascii=False, indent=2)


@tool
def list_doctors(department: str | None = None) -> str:
    """列出医生（可按科室过滤）。

    Args:
        department: 科室名称（中文，如 '心内科'）。None 表示全部医生

    Returns:
        JSON 字符串：医生列表，每项含 id / name / department / title / specialty
    """
    from medical_agent.db.database import get_db

    db = get_db()
    repo = DoctorRepository(db)
    if department:
        doctors = repo.list_by_department(department)
    else:
        doctors = repo.list_all()
    return json.dumps(doctors, ensure_ascii=False, indent=2)


@tool
def check_availability(
    department: str,
    start_date: str,
    end_date: str | None = None,
    time_slot: str | None = None,
) -> str:
    """查询某科室在指定日期范围内的可用排班。

    Args:
        department: 科室名称（中文）
        start_date: 起始日期 'YYYY-MM-DD'
        end_date: 结束日期 'YYYY-MM-DD'，None 表示只查 start_date 当天
        time_slot: 时段过滤 'morning' / 'afternoon' / 'evening'，None 表示全部

    Returns:
        JSON 字符串：可用排班列表，每项含 doctor_id / doctor_name / date / time_slot / remaining
    """
    from medical_agent.db.database import get_db

    db = get_db()
    repo = ScheduleRepository(db)
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date) if end_date else start

    schedules = repo.find_available(
        department=department,
        start_date=start,
        end_date=end,
        time_slot=time_slot,
    )
    return json.dumps(schedules, ensure_ascii=False, indent=2)


def all_scheduling_tools() -> list:
    """返回所有排班工具，供 Agent 注入。"""
    return [list_departments, list_doctors, check_availability]
