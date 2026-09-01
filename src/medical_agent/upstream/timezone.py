"""时区处理。

v2：所有时间统一用 Asia/Shanghai 存 + 显示。
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


# 医院所在时区（中国大陆医院默认）
HOSPITAL_TZ = ZoneInfo("Asia/Shanghai")
UTC_TZ = ZoneInfo("UTC")


def now_in_hospital_tz() -> datetime:
    """当前医院时区时间。"""
    return datetime.now(HOSPITAL_TZ)


def today_in_hospital_tz() -> date:
    """当前医院时区的日期。"""
    return now_in_hospital_tz().date()


def to_hospital_tz(dt: datetime) -> datetime:
    """任意 datetime 转医院时区。"""
    if dt.tzinfo is None:
        # naive datetime 假定为 UTC
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(HOSPITAL_TZ)


def format_slot_time(date_: date, time_slot: str) -> str:
    """格式化时段为人类可读字符串。"""
    from medical_agent.db.repositories import TIME_SLOT_HOURS

    start, end = TIME_SLOT_HOURS[time_slot]
    return f"{date_.isoformat()} {start}-{end}"


def is_future_slot(date_: date, time_slot: str) -> bool:
    """判断某时段是否在未来（防止预约过期时段）。"""
    from medical_agent.db.repositories import TIME_SLOT_HOURS

    start_time_str = TIME_SLOT_HOURS[time_slot][0]
    hour, minute = map(int, start_time_str.split(":"))
    slot_datetime = datetime.combine(
        date_, datetime.min.time().replace(hour=hour, minute=minute)
    ).replace(tzinfo=HOSPITAL_TZ)
    return slot_datetime > now_in_hospital_tz()
