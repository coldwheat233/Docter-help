"""模拟医院 HIS 系统。

提供：
- HISMocker 类：模拟 HIS 推过来的排班变更
- handle_schedule_change(): 接收 HIS webhook 推过来的数据，写入 upstream_changes 表
- 同步修改 schedules 表（带乐观锁）

第 1 周 mock：直接用 Python 函数调；
生产化：换成 FastAPI 端点 + 真实 webhook。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from medical_agent.db.repositories import (
    OptimisticLockError,
    ScheduleRepository,
    UpstreamChangeRepository,
)


class HISMocker:
    """HIS 系统模拟器。"""

    def __init__(self, conn):
        self.conn = conn
        self.schedule_repo = ScheduleRepository(conn)
        self.upstream_repo = UpstreamChangeRepository(conn)

    def doctor_cancel_schedule(
        self,
        schedule_id: int,
        expected_version: int,
        reason: str = "doctor_leave",
    ) -> bool:
        """医生请假：取消某 schedule（标 is_available=0）。

        Args:
            schedule_id: 排班 ID
            expected_version: HIS 端读到的版本号
            reason: 请假原因

        Returns:
            True 成功 / False 失败
        """
        try:
            new_version = self.schedule_repo.update(
                schedule_id=schedule_id,
                expected_version=expected_version,
                is_available=False,
            )
        except OptimisticLockError as e:
            return False

        # 记录上游变更
        self.upstream_repo.record(
            source="his",
            entity_type="schedule",
            entity_id=str(schedule_id),
            change_type="update",
            new_state={"is_available": False, "version": new_version, "reason": reason},
        )

        # 通知下游（mock）
        from medical_agent.downstream.notifier import notify_schedule_changed
        notify_schedule_changed(schedule_id, "disabled")

        return True

    def adjust_capacity(
        self,
        schedule_id: int,
        expected_version: int,
        new_capacity: int,
        reason: str = "demand_high",
    ) -> bool:
        """号源扩容：调整某 schedule 的 capacity。"""
        try:
            new_version = self.schedule_repo.update(
                schedule_id=schedule_id,
                expected_version=expected_version,
                capacity=new_capacity,
            )
        except OptimisticLockError as e:
            return False

        self.upstream_repo.record(
            source="his",
            entity_type="schedule",
            entity_id=str(schedule_id),
            change_type="update",
            new_state={"capacity": new_capacity, "version": new_version, "reason": reason},
        )
        from medical_agent.downstream.notifier import notify_schedule_changed
        notify_schedule_changed(schedule_id, "capacity_changed")
        return True

    def restore_schedule(
        self,
        schedule_id: int,
        expected_version: int,
    ) -> bool:
        """恢复被取消的排班。"""
        try:
            new_version = self.schedule_repo.update(
                schedule_id=schedule_id,
                expected_version=expected_version,
                is_available=True,
            )
        except OptimisticLockError:
            return False

        self.upstream_repo.record(
            source="his",
            entity_type="schedule",
            entity_id=str(schedule_id),
            change_type="update",
            new_state={"is_available": True, "version": new_version},
        )
        from medical_agent.downstream.notifier import notify_schedule_changed
        notify_schedule_changed(schedule_id, "restored")
        return True


# =====================================================================
# 演示脚本：模拟 HIS 推排班变更
# =====================================================================
def demo_his_workflow():
    """演示：HIS 取消一个 schedule，Agent 落库前会感知到。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        ScheduleRepository,
    )

    db = get_db()

    # 准备：1 个 schedule
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    sched_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )

    his = HISMocker(db)

    # Step 1: 读 schedule（拿到 version=0）
    s = ScheduleRepository(db).get_by_id(sched_id)
    print(f"[his_demo] schedule 初始 version={s['version']}, is_available={s['is_available']}")

    # Step 2: 模拟医生请假，HIS 推过来
    success = his.doctor_cancel_schedule(sched_id, expected_version=0, reason="医生请假")
    print(f"[his_demo] 医生请假 API 调用 success={success}")

    # Step 3: 验证 schedule 状态
    s = ScheduleRepository(db).get_by_id(sched_id)
    print(f"[his_demo] 医生请假后 version={s['version']}, is_available={s['is_available']}")

    # Step 4: Agent 调 set_appointment，应该被 re-check 拦截
    print("[his_demo] 模拟 Agent 落库：")
    result = AppointmentRepository(db).create(
        patient_id="P001", doctor_id=doctor_id, schedule_id=sched_id
    )
    print(f"[his_demo] 落库结果: {result}（预期抛 OptimisticLockError）")


if __name__ == "__main__":
    demo_his_workflow()
