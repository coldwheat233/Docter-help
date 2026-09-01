"""5 个 Repository + 审计日志 + 乐观锁 + 幂等性。

v2 增强：
- ScheduleRepository.decrement_remaining 用乐观锁（CAS）
- AppointmentRepository.create 用事务 + 幂等性检查
- 新增 AuditLogRepository
- 新增 UpstreamChangeRepository
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any


# =====================================================================
# 自定义异常
# =====================================================================
class RepositoryError(Exception):
    """Repository 通用异常。"""


class OptimisticLockError(RepositoryError):
    """乐观锁冲突：版本号不匹配或剩余号源不足。"""


class IdempotencyConflictError(RepositoryError):
    """幂等键冲突：同一 key 关联到不同参数。"""


class InvalidStatusTransitionError(RepositoryError):
    """预约状态机非法转换。"""


# =====================================================================
# 工具函数
# =====================================================================
def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [_row_to_dict(r) for r in rows]


def _generate_appointment_id() -> str:
    """生成预约单号：A + YYYYMMDD + 4 位随机。"""
    today = datetime.now().strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"A{today}{suffix}"


def _generate_idempotency_key(prefix: str = "") -> str:
    """生成幂等键。"""
    return f"{prefix}{uuid.uuid4().hex}"


# =====================================================================
# 状态机
# =====================================================================
VALID_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"confirmed", "cancelled"},
    "confirmed": {"cancelled", "completed", "no_show"},
    "cancelled": {"pending"},  # v2: 允许恢复
    "completed": set(),  # 终态
    "no_show": set(),    # 终态
}


def validate_status_transition(current: str, target: str) -> None:
    """校验状态机转换合法性。抛 InvalidStatusTransitionError。"""
    if target not in VALID_STATUS_TRANSITIONS.get(current, set()):
        raise InvalidStatusTransitionError(
            f"非法状态转换: {current} → {target}（允许: {VALID_STATUS_TRANSITIONS.get(current, set())}）"
        )


# =====================================================================
# 1. DepartmentRepository
# =====================================================================
class DepartmentRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_all(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM departments ORDER BY id")
        return _rows_to_list(cur.fetchall())

    def get_by_name(self, name: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM departments WHERE name = ?", (name,))
        return _row_to_dict(cur.fetchone())

    def create(self, code: str, name: str, description: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO departments (code, name, description) VALUES (?, ?, ?)",
            (code, name, description),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore


# =====================================================================
# 2. DoctorRepository
# =====================================================================
class DoctorRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_all(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM doctors WHERE is_active = 1 ORDER BY id")
        return _rows_to_list(cur.fetchall())

    def list_by_department(self, department: str) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM doctors WHERE department = ? AND is_active = 1 ORDER BY id",
            (department,),
        )
        return _rows_to_list(cur.fetchall())

    def get_by_id(self, doctor_id: int) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,))
        return _row_to_dict(cur.fetchone())

    def create(
        self,
        name: str,
        department: str,
        title: str = "主治医师",
        specialty: str = "",
        intro: str = "",
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO doctors (name, department, title, specialty, intro)
               VALUES (?, ?, ?, ?, ?)""",
            (name, department, title, specialty, intro),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore


# =====================================================================
# 3. ScheduleRepository（v2 乐观锁）
# =====================================================================
TIME_SLOT_HOURS = {
    "morning": ("08:00", "12:00"),
    "afternoon": ("14:00", "18:00"),
    "evening": ("18:30", "21:00"),
}


class ScheduleRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def find_available(
        self,
        department: str,
        start_date: date,
        end_date: date,
        time_slot: str | None = None,
        min_remaining: int = 1,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT
                s.id          AS schedule_id,
                s.doctor_id,
                s.version     AS schedule_version,
                d.name        AS doctor_name,
                d.department,
                d.title       AS doctor_title,
                s.schedule_date,
                s.time_slot,
                s.start_time,
                s.end_time,
                s.remaining,
                s.capacity,
                s.is_available
            FROM schedules s
            JOIN doctors d ON d.id = s.doctor_id
            WHERE d.department = ?
              AND s.schedule_date BETWEEN ? AND ?
              AND s.is_available = 1
              AND s.remaining >= ?
        """
        params: list[Any] = [department, start_date.isoformat(), end_date.isoformat(), min_remaining]
        if time_slot:
            sql += " AND s.time_slot = ?"
            params.append(time_slot)
        sql += " ORDER BY s.schedule_date, s.time_slot, d.id"
        cur = self.conn.execute(sql, params)
        return _rows_to_list(cur.fetchall())

    def get_by_id(self, schedule_id: int) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        return _row_to_dict(cur.fetchone())

    def get_version(self, schedule_id: int) -> int | None:
        """获取当前版本号。"""
        cur = self.conn.execute("SELECT version FROM schedules WHERE id = ?", (schedule_id,))
        row = cur.fetchone()
        return row["version"] if row else None

    def create(
        self,
        doctor_id: int,
        schedule_date: date,
        time_slot: str,
        capacity: int = 20,
        is_holiday: bool = False,
    ) -> int:
        start, end = TIME_SLOT_HOURS[time_slot]
        cur = self.conn.execute(
            """INSERT INTO schedules
               (doctor_id, schedule_date, time_slot, start_time, end_time,
                capacity, remaining, is_holiday, version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                doctor_id,
                schedule_date.isoformat(),
                time_slot,
                start,
                end,
                capacity,
                capacity,
                is_holiday,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    # -------- v2: 乐观锁 CAS --------
    def decrement_remaining(
        self,
        schedule_id: int,
        expected_version: int | None = None,
        by: int = 1,
    ) -> tuple[bool, int | None]:
        """乐观锁扣号源。

        Args:
            schedule_id: 排班 ID
            expected_version: 期望的版本号；None 表示不校验版本（不推荐）
            by: 扣减数量

        Returns:
            (success, new_version)
            - success=True: 扣减成功，返回 new_version
            - success=False: 失败（库存不足或版本冲突），new_version=None

        Raises:
            OptimisticLockError: 排班被删除或不可用
        """
        # 先读当前状态
        cur = self.conn.execute(
            "SELECT version, remaining, is_available FROM schedules WHERE id = ?",
            (schedule_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise OptimisticLockError(f"schedule {schedule_id} 不存在")
        if not row["is_available"]:
            raise OptimisticLockError(f"schedule {schedule_id} 已停用")

        current_version = row["version"]
        current_remaining = row["remaining"]

        # 版本校验
        if expected_version is not None and expected_version != current_version:
            raise OptimisticLockError(
                f"schedule {schedule_id} 版本冲突：期望 {expected_version}，实际 {current_version}"
            )

        # 库存校验
        if current_remaining < by:
            raise OptimisticLockError(
                f"schedule {schedule_id} 库存不足：剩余 {current_remaining}，需要 {by}"
            )

        # CAS 更新
        new_version = current_version + 1
        cur = self.conn.execute(
            """UPDATE schedules
               SET remaining = remaining - ?,
                   version = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?
                 AND version = ?
                 AND remaining >= ?""",
            (by, new_version, schedule_id, current_version, by),
        )

        if cur.rowcount == 0:
            # CAS 失败（其他事务抢到了）
            self.conn.rollback()
            raise OptimisticLockError(
                f"schedule {schedule_id} CAS 失败：版本 {current_version} 已被修改"
            )

        self.conn.commit()
        return True, new_version

    def increment_remaining(
        self,
        schedule_id: int,
        by: int = 1,
    ) -> tuple[bool, int | None]:
        """退回号源（取消/改约时用）。

        与 decrement 不同，increment 不要求 expected_version（因为是被动回退）。
        """
        cur = self.conn.execute(
            "SELECT version FROM schedules WHERE id = ?",
            (schedule_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise OptimisticLockError(f"schedule {schedule_id} 不存在")

        new_version = row["version"] + 1
        cur = self.conn.execute(
            """UPDATE schedules
               SET remaining = remaining + ?,
                   version = ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (by, new_version, schedule_id),
        )
        if cur.rowcount == 0:
            self.conn.rollback()
            raise OptimisticLockError(f"schedule {schedule_id} 退回失败")
        self.conn.commit()
        return True, new_version

    def update(
        self,
        schedule_id: int,
        expected_version: int,
        is_available: bool | None = None,
        capacity: int | None = None,
        is_holiday: bool | None = None,
    ) -> int:
        """上游变更（医生请假、号源调整）走这里。

        用乐观锁防止覆盖并发修改。

        Returns:
            新版本号

        Raises:
            OptimisticLockError: 版本冲突
        """
        cur = self.conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        row = cur.fetchone()
        if row is None:
            raise OptimisticLockError(f"schedule {schedule_id} 不存在")
        if row["version"] != expected_version:
            raise OptimisticLockError(
                f"schedule {schedule_id} 版本冲突：期望 {expected_version}，实际 {row['version']}"
            )

        # 构造 SET 子句
        sets: list[str] = []
        params: list[Any] = []
        if is_available is not None:
            sets.append("is_available = ?")
            params.append(is_available)
        if capacity is not None:
            sets.append("capacity = ?")
            params.append(capacity)
            # 同步调整 remaining（保留已预约的）
            delta = capacity - row["capacity"]
            new_remaining = max(0, row["remaining"] + delta)
            sets.append("remaining = ?")
            params.append(new_remaining)
        if is_holiday is not None:
            sets.append("is_holiday = ?")
            params.append(is_holiday)

        if not sets:
            return row["version"]  # 无更新

        new_version = row["version"] + 1
        sets.append("version = ?")
        params.append(new_version)
        sets.append("updated_at = CURRENT_TIMESTAMP")
        params.append(schedule_id)
        params.append(expected_version)

        cur = self.conn.execute(
            f"UPDATE schedules SET {', '.join(sets)} WHERE id = ? AND version = ?",
            params,
        )
        if cur.rowcount == 0:
            self.conn.rollback()
            raise OptimisticLockError(
                f"schedule {schedule_id} CAS 失败：版本 {expected_version} 已被修改"
            )
        self.conn.commit()
        return new_version

    def count_total(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) AS c FROM schedules")
        return cur.fetchone()["c"]


# =====================================================================
# 4. PatientRepository
# =====================================================================
class PatientRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_by_id(self, patient_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,))
        return _row_to_dict(cur.fetchone())

    def upsert(self, patient_id: str, name: str, phone: str = "", **kwargs: Any) -> None:
        cur = self.conn.execute(
            "SELECT id FROM patients WHERE id = ?", (patient_id,)
        )
        if cur.fetchone() is None:
            self.conn.execute(
                """INSERT INTO patients (id, name, phone, insurance_no, birth_date, gender)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    patient_id,
                    name,
                    phone,
                    kwargs.get("insurance_no", ""),
                    kwargs.get("birth_date"),
                    kwargs.get("gender"),
                ),
            )
        else:
            self.conn.execute(
                """UPDATE patients
                   SET name = ?, phone = ?, insurance_no = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (name, phone, kwargs.get("insurance_no", ""), patient_id),
            )
        self.conn.commit()

    def list_all(self) -> list[dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM patients ORDER BY created_at DESC LIMIT 100")
        return _rows_to_list(cur.fetchall())


# =====================================================================
# 5. AppointmentRepository（v2：事务 + 幂等性 + 状态机）
# =====================================================================
class AppointmentRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        """幂等性检查：先用 key 查。"""
        if not key:
            return None
        cur = self.conn.execute(
            "SELECT * FROM appointments WHERE idempotency_key = ?", (key,)
        )
        return _row_to_dict(cur.fetchone())

    def create(
        self,
        patient_id: str,
        doctor_id: int,
        schedule_id: int,
        expected_schedule_version: int | None = None,
        symptoms: str = "",
        duration: str = "",
        severity: str = "",
        idempotency_key: str | None = None,
    ) -> str:
        """创建预约。事务原子性 + 乐观锁 + 幂等性。

        Args:
            patient_id, doctor_id, schedule_id: 必填
            expected_schedule_version: 期望的 schedule 版本号（v2 校验）
            symptoms, duration, severity: 问诊信息
            idempotency_key: 幂等键（v2 防重入）；同 key 重复调用返回原 appointment_id

        Returns:
            appointment_id

        Raises:
            IdempotencyConflictError: 幂等键已存在但参数不同
            OptimisticLockError: schedule 版本冲突 / 库存不足
        """
        # 1. 幂等性检查
        if idempotency_key:
            existing = self.get_by_idempotency_key(idempotency_key)
            if existing:
                # 校验关键参数一致
                if (
                    existing["patient_id"] == patient_id
                    and existing["doctor_id"] == doctor_id
                    and existing["schedule_id"] == schedule_id
                ):
                    return existing["id"]  # 幂等命中，返回原 ID
                else:
                    raise IdempotencyConflictError(
                        f"幂等键 {idempotency_key} 已存在但参数不同："
                        f"原 ({existing['patient_id']}, dr={existing['doctor_id']}, sched={existing['schedule_id']}) "
                        f"新 ({patient_id}, dr={doctor_id}, sched={schedule_id})"
                    )

        # 2. 事务开始
        try:
            self.conn.execute("BEGIN IMMEDIATE")  # 拿写锁

            # 3. 校验 schedule 版本
            cur = self.conn.execute(
                "SELECT version, remaining, is_available FROM schedules WHERE id = ?",
                (schedule_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise OptimisticLockError(f"schedule {schedule_id} 不存在")
            if not row["is_available"]:
                raise OptimisticLockError(f"schedule {schedule_id} 已停用")
            if (
                expected_schedule_version is not None
                and row["version"] != expected_schedule_version
            ):
                raise OptimisticLockError(
                    f"schedule {schedule_id} 版本冲突：期望 {expected_schedule_version}，实际 {row['version']}"
                )
            if row["remaining"] < 1:
                raise OptimisticLockError(f"schedule {schedule_id} 库存不足")

            # 4. 扣号源（CAS）
            new_version = row["version"] + 1
            cur = self.conn.execute(
                """UPDATE schedules
                   SET remaining = remaining - 1,
                       version = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND version = ? AND remaining >= 1""",
                (new_version, schedule_id, row["version"]),
            )
            if cur.rowcount == 0:
                raise OptimisticLockError(f"schedule {schedule_id} CAS 失败")

            # 5. 写预约
            appt_id = _generate_appointment_id()
            effective_key = idempotency_key or _generate_idempotency_key(prefix="auto-")
            self.conn.execute(
                """INSERT INTO appointments
                   (id, patient_id, doctor_id, schedule_id, schedule_version,
                    symptoms, duration, severity, status, confirmed_at, idempotency_key)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', CURRENT_TIMESTAMP, ?)""",
                (
                    appt_id,
                    patient_id,
                    doctor_id,
                    schedule_id,
                    new_version,
                    symptoms,
                    duration,
                    severity,
                    effective_key,
                ),
            )

            # 6. 写审计日志
            self._write_audit(
                event_type="appointment.create",
                entity_type="appointment",
                entity_id=appt_id,
                actor=f"patient:{patient_id}",
                action="create",
                before_state=None,
                after_state={"status": "confirmed", "schedule_id": schedule_id},
                metadata={"schedule_version": new_version, "idempotency_key": effective_key},
            )

            # 7. 提交
            self.conn.commit()
            return appt_id

        except Exception:
            self.conn.rollback()
            raise

    def get_by_id(self, appointment_id: str) -> dict[str, Any] | None:
        cur = self.conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,))
        return _row_to_dict(cur.fetchone())

    def list_by_patient(
        self, patient_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        if status:
            cur = self.conn.execute(
                "SELECT * FROM appointments WHERE patient_id = ? AND status = ? ORDER BY created_at DESC",
                (patient_id, status),
            )
        else:
            cur = self.conn.execute(
                "SELECT * FROM appointments WHERE patient_id = ? ORDER BY created_at DESC",
                (patient_id,),
            )
        return _rows_to_list(cur.fetchall())

    def update_status(
        self,
        appointment_id: str,
        status: str,
        cancelled_reason: str | None = None,
        actor: str = "system",
    ) -> None:
        """修改状态（带状态机校验）。"""
        current = self.get_by_id(appointment_id)
        if current is None:
            raise RepositoryError(f"appointment {appointment_id} 不存在")
        validate_status_transition(current["status"], status)

        before_state = {"status": current["status"]}

        if status == "cancelled":
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                self.conn.execute(
                    """UPDATE appointments
                       SET status = ?, cancelled_at = CURRENT_TIMESTAMP,
                           cancelled_reason = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (status, cancelled_reason, appointment_id),
                )
                # 退回号源
                ScheduleRepository(self.conn).increment_remaining(current["schedule_id"])
                self._write_audit(
                    event_type="appointment.cancel",
                    entity_type="appointment",
                    entity_id=appointment_id,
                    actor=actor,
                    action="cancel",
                    before_state=before_state,
                    after_state={"status": status, "reason": cancelled_reason},
                    metadata={},
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        else:
            self.conn.execute(
                """UPDATE appointments
                   SET status = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (status, appointment_id),
            )
            self._write_audit(
                event_type=f"appointment.{status}",
                entity_type="appointment",
                entity_id=appointment_id,
                actor=actor,
                action=status,
                before_state=before_state,
                after_state={"status": status},
                metadata={},
            )
            self.conn.commit()

    def restore(self, appointment_id: str, actor: str = "system") -> bool:
        """恢复已取消的预约（v2 新增）。

        限制：
        - 状态必须是 cancelled
        - 取消时间在 24h 内
        - 目标 schedule 仍然可用且有库存

        Returns:
            True 成功 / False 不满足恢复条件
        """
        appt = self.get_by_id(appointment_id)
        if appt is None:
            raise RepositoryError(f"appointment {appointment_id} 不存在")
        if appt["status"] != "cancelled":
            return False

        # 校验 24h 内
        if appt.get("cancelled_at"):
            cancelled_time = appt["cancelled_at"]
            if isinstance(cancelled_time, str):
                cancelled_time = datetime.fromisoformat(cancelled_time)
            if datetime.now() - cancelled_time > timedelta(hours=24):
                return False

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # 校验 schedule 仍可用
            cur = self.conn.execute(
                "SELECT version, remaining, is_available FROM schedules WHERE id = ?",
                (appt["schedule_id"],),
            )
            sched = cur.fetchone()
            if sched is None or not sched["is_available"] or sched["remaining"] < 1:
                self.conn.rollback()
                return False

            # 扣号源
            new_version = sched["version"] + 1
            cur = self.conn.execute(
                """UPDATE schedules
                   SET remaining = remaining - 1, version = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND version = ? AND remaining >= 1""",
                (new_version, appt["schedule_id"], sched["version"]),
            )
            if cur.rowcount == 0:
                self.conn.rollback()
                return False

            # 改状态
            self.conn.execute(
                """UPDATE appointments
                   SET status = 'confirmed', cancelled_at = NULL, cancelled_reason = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (appointment_id,),
            )
            self._write_audit(
                event_type="appointment.restore",
                entity_type="appointment",
                entity_id=appointment_id,
                actor=actor,
                action="restore",
                before_state={"status": "cancelled"},
                after_state={"status": "confirmed"},
                metadata={},
            )
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def update_schedule(
        self,
        appointment_id: str,
        new_schedule_id: int,
        actor: str = "system",
    ) -> None:
        """改约到新时段。"""
        appt = self.get_by_id(appointment_id)
        if appt is None:
            raise RepositoryError(f"appointment {appointment_id} 不存在")
        if appt["status"] != "confirmed":
            raise InvalidStatusTransitionError(
                f"只有 confirmed 状态可改约，当前状态 {appt['status']}"
            )

        old_schedule_id = appt["schedule_id"]
        if old_schedule_id == new_schedule_id:
            return  # 无变化

        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # 1. 校验新 schedule
            cur = self.conn.execute(
                "SELECT version, remaining, is_available FROM schedules WHERE id = ?",
                (new_schedule_id,),
            )
            new_sched = cur.fetchone()
            if new_sched is None:
                raise OptimisticLockError(f"new schedule {new_schedule_id} 不存在")
            if not new_sched["is_available"]:
                raise OptimisticLockError(f"new schedule {new_schedule_id} 已停用")
            if new_sched["remaining"] < 1:
                raise OptimisticLockError(f"new schedule {new_schedule_id} 库存不足")

            # 2. 扣新 schedule
            new_version = new_sched["version"] + 1
            cur = self.conn.execute(
                """UPDATE schedules
                   SET remaining = remaining - 1, version = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND version = ? AND remaining >= 1""",
                (new_version, new_schedule_id, new_sched["version"]),
            )
            if cur.rowcount == 0:
                raise OptimisticLockError(f"new schedule CAS 失败")

            # 3. 退旧 schedule
            ScheduleRepository(self.conn).increment_remaining(old_schedule_id)

            # 4. 更新 appointment
            self.conn.execute(
                """UPDATE appointments
                   SET schedule_id = ?, schedule_version = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (new_schedule_id, new_version, appointment_id),
            )

            # 5. 审计
            self._write_audit(
                event_type="appointment.reschedule",
                entity_type="appointment",
                entity_id=appointment_id,
                actor=actor,
                action="reschedule",
                before_state={"schedule_id": old_schedule_id},
                after_state={"schedule_id": new_schedule_id},
                metadata={"new_schedule_version": new_version},
            )

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _write_audit(
        self,
        event_type: str,
        entity_type: str,
        entity_id: str,
        actor: str,
        action: str,
        before_state: dict | None,
        after_state: dict | None,
        metadata: dict,
    ) -> None:
        """写审计日志（在事务内调用）。"""
        self.conn.execute(
            """INSERT INTO audit_log
               (event_type, entity_type, entity_id, actor, action,
                before_state, after_state, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_type,
                entity_type,
                entity_id,
                actor,
                action,
                json.dumps(before_state, ensure_ascii=False) if before_state else None,
                json.dumps(after_state, ensure_ascii=False) if after_state else None,
                json.dumps(metadata, ensure_ascii=False),
            ),
        )

    def count_total(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) AS c FROM appointments")
        return cur.fetchone()["c"]

    def count_by_status(self, status: str) -> int:
        cur = self.conn.execute(
            "SELECT COUNT(*) AS c FROM appointments WHERE status = ?", (status,)
        )
        return cur.fetchone()["c"]


# =====================================================================
# 6. AuditLogRepository（v2 新增）
# =====================================================================
class AuditLogRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_by_entity(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            """SELECT * FROM audit_log
               WHERE entity_type = ? AND entity_id = ?
               ORDER BY created_at DESC""",
            (entity_type, entity_id),
        )
        return _rows_to_list(cur.fetchall())

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return _rows_to_list(cur.fetchall())

    def count_total(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) AS c FROM audit_log")
        return cur.fetchone()["c"]


# =====================================================================
# 7. UpstreamChangeRepository（v2 新增）
# =====================================================================
class UpstreamChangeRepository:
    """上游变更通知（HIS / 医生自助端 / 运维）。"""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(
        self,
        source: str,
        entity_type: str,
        entity_id: str,
        change_type: str,
        new_state: dict[str, Any] | None = None,
    ) -> int:
        """记录一条上游变更。"""
        cur = self.conn.execute(
            """INSERT INTO upstream_changes
               (source, entity_type, entity_id, change_type, new_state)
               VALUES (?, ?, ?, ?, ?)""",
            (
                source,
                entity_type,
                entity_id,
                change_type,
                json.dumps(new_state, ensure_ascii=False) if new_state else None,
            ),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore

    def list_pending_for_entity(
        self, entity_type: str, entity_id: str
    ) -> list[dict[str, Any]]:
        """查某实体的未应用变更（Agent 落库前 re-check 用）。"""
        cur = self.conn.execute(
            """SELECT * FROM upstream_changes
               WHERE entity_type = ? AND entity_id = ? AND applied = 0
               ORDER BY created_at ASC""",
            (entity_type, entity_id),
        )
        return _rows_to_list(cur.fetchall())

    def mark_applied(self, change_id: int) -> None:
        self.conn.execute(
            "UPDATE upstream_changes SET applied = 1 WHERE id = ?", (change_id,)
        )
        self.conn.commit()

    def has_pending_change(self, entity_type: str, entity_id: str) -> bool:
        return len(self.list_pending_for_entity(entity_type, entity_id)) > 0
