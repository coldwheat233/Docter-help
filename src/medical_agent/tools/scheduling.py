"""排班相关工具（只读）+ select_slot（选定时段写入 state）。

v4 新增 select_slot：补上"用户选时段 → 落 state"的断点，
让 confirmer 的 set_appointment 能从 state.selected_slot 拿到完整参数。
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langchain_core.tools import InjectedToolCallId
from langgraph.types import Command

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

    # 不允许预约过去的日期（ clamps 到今天）
    today = date.today()
    if start < today:
        start = today
    if end < start:
        end = start

    schedules = repo.find_available(
        department=department,
        start_date=start,
        end_date=end,
        time_slot=time_slot,
    )
    return json.dumps(schedules, ensure_ascii=False, indent=2)


@tool
def select_slot(
    schedule_id: int,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """用户从候选中选定某个时段后调用：把所选时段写入 state.selected_slot。

    这是"时间推荐 → 预约确认"之间的桥：不写库、无副作用，
    只把用户选定的排班（含 doctor_id / schedule_version 等内部字段）记录到状态里，
    后续 confirmer 调 set_appointment() 时会自动从 state 取这些参数。

    Args:
        schedule_id: 用户选定的排班 ID（来自 check_availability 结果的 schedule_id 字段）

    Returns:
        人类可读的确认文本（已选择某医生某时段）
    """
    from medical_agent.db.database import get_db

    db = get_db()
    schedule = ScheduleRepository(db).get_by_id(schedule_id)
    if schedule is None:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"排班 {schedule_id} 不存在，请重新用 check_availability 查询后再让用户选择",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    doctor = DoctorRepository(db).get_by_id(schedule["doctor_id"]) or {}
    slot: dict[str, Any] = {
        "schedule_id": schedule["id"],
        "doctor_id": schedule["doctor_id"],
        "schedule_version": schedule["version"],
        "schedule_date": schedule["schedule_date"],
        "time_slot": schedule["time_slot"],
        "start_time": schedule["start_time"],
        "end_time": schedule["end_time"],
        "doctor_name": doctor.get("name", ""),
        "doctor_title": doctor.get("title", ""),
        "department": doctor.get("department", ""),
    }
    human_text = (
        f"已记录选定时段：{slot['schedule_date']} {slot['start_time']}-{slot['end_time']} "
        f"{slot['doctor_name']}（{slot['doctor_title']}，{slot['department']}）。"
        f"接下来请复述预约详情并询问用户是否确认。"
    )
    return Command(
        update={
            "selected_slot": slot,
            "current_step": "confirm",
            "messages": [ToolMessage(content=human_text, tool_call_id=tool_call_id)],
        }
    )


def all_scheduling_tools() -> list:
    """返回所有排班工具，供 Agent 注入。"""
    return [list_departments, list_doctors, check_availability, select_slot]
