"""下游通知层（mock）。

v2：所有写操作完成后调这里。生产可改为：
- 短信/微信通知
- 邮件
- WebSocket 推给医生端
- 推给医院 HIS
- 推给财务/医保系统

第 1 周 mock：仅打印到日志 + 写入 notification_log（in-memory）。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger("notifier")

# 内存通知日志（不持久化，重启清空）
_notification_log: list[dict[str, Any]] = []


def notify_appointment_created(appointment_id: str) -> None:
    """通知：预约已创建。"""
    msg = {
        "type": "appointment.created",
        "appointment_id": appointment_id,
        "timestamp": datetime.now().isoformat(),
        "channels": ["sms_to_patient", "app_push", "his_sync"],
    }
    _notification_log.append(msg)
    logger.info(f"[notify] {msg}")


def notify_appointment_cancelled(appointment_id: str, reason: str) -> None:
    """通知：预约已取消。"""
    msg = {
        "type": "appointment.cancelled",
        "appointment_id": appointment_id,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "channels": ["sms_to_patient", "refund_trigger"],
    }
    _notification_log.append(msg)
    logger.info(f"[notify] {msg}")


def notify_appointment_rescheduled(appointment_id: str, new_schedule_id: int) -> None:
    """通知：预约已改约。"""
    msg = {
        "type": "appointment.rescheduled",
        "appointment_id": appointment_id,
        "new_schedule_id": new_schedule_id,
        "timestamp": datetime.now().isoformat(),
        "channels": ["sms_to_patient", "app_push"],
    }
    _notification_log.append(msg)
    logger.info(f"[notify] {msg}")


def notify_schedule_changed(schedule_id: int, change_type: str) -> None:
    """通知：排班变更（给已预约的患者）。"""
    msg = {
        "type": "schedule.changed",
        "schedule_id": schedule_id,
        "change_type": change_type,
        "timestamp": datetime.now().isoformat(),
        "channels": ["sms_to_affected_patients"],
    }
    _notification_log.append(msg)
    logger.info(f"[notify] {msg}")


def get_recent_notifications(limit: int = 20) -> list[dict[str, Any]]:
    """读最近的 N 条通知（测试用）。"""
    return _notification_log[-limit:]


def clear_notifications() -> None:
    """清空通知日志（测试用）。"""
    _notification_log.clear()
