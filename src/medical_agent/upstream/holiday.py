"""节假日规则（中国法定节假日）。

v2：seed 生成排班时按节假日规则跳过（节假日不出诊）。
"""

from __future__ import annotations

from datetime import date


# 2026 年中国法定节假日（简化版，仅覆盖 1-2 个示例）
HOLIDAYS_2026: set[date] = {
    date(2026, 1, 1),   # 元旦
    date(2026, 1, 2),
    date(2026, 1, 3),
    date(2026, 2, 16),  # 春节（示例）
    date(2026, 2, 17),
    date(2026, 2, 18),
    date(2026, 4, 4),   # 清明
    date(2026, 4, 5),
    date(2026, 4, 6),
    date(2026, 5, 1),   # 劳动节
    date(2026, 5, 2),
    date(2026, 5, 3),
    date(2026, 6, 19),  # 端午（示例）
    date(2026, 6, 20),
    date(2026, 6, 21),
    date(2026, 9, 25),  # 中秋（示例）
    date(2026, 9, 26),
    date(2026, 9, 27),
    date(2026, 10, 1),  # 国庆
    date(2026, 10, 2),
    date(2026, 10, 3),
    date(2026, 10, 4),
    date(2026, 10, 5),
    date(2026, 10, 6),
    date(2026, 10, 7),
}


def is_holiday(d: date) -> bool:
    """判断某天是否法定节假日。"""
    return d in HOLIDAYS_2026


def is_workday(d: date) -> bool:
    """判断某天是否工作日（非周末、非节假日）。"""
    if d.weekday() >= 5:  # 周六周日
        return False
    if is_holiday(d):
        return False
    return True
