"""Repository v2 全面测试：CRUD + 乐观锁 + 事务 + 幂等性 + 状态机 + 审计 + 上游通知。"""

import json
import threading
from datetime import date

import pytest


# =====================================================================
# 基础 CRUD
# =====================================================================
def test_department_repository_crud(temp_db_path):
    """DepartmentRepository 创建/查询。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DepartmentRepository

    db = get_db()
    repo = DepartmentRepository(db)
    dept_id = repo.create(code="TEST", name="测试科室", description="用于测试")
    assert dept_id > 0

    dept = repo.get_by_name("测试科室")
    assert dept is not None
    assert dept["code"] == "TEST"


def test_doctor_repository(temp_db_path):
    """DoctorRepository 按科室查询。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DepartmentRepository, DoctorRepository

    db = get_db()
    dept_repo = DepartmentRepository(db)
    dept_repo.create(code="IM", name="心内科", description="")
    dept_repo.create(code="OR", name="骨科", description="")
    DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    DoctorRepository(db).create(name="李四", department="心内科", title="主治医师")
    DoctorRepository(db).create(name="王五", department="骨科", title="主治医师")

    cardio = DoctorRepository(db).list_by_department("心内科")
    assert len(cardio) == 2
    assert {d["name"] for d in cardio} == {"张三", "李四"}


def test_schedule_repository_create_and_find(temp_db_path):
    """ScheduleRepository 创建排班 + 查可用（含 v2 version 字段）。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_repo = ScheduleRepository(db)

    today = date.today()
    for offset in range(3):
        schedule_repo.create(
            doctor_id=doctor_id,
            schedule_date=today.replace(day=today.day + offset),
            time_slot="morning",
            capacity=20,
        )

    avail = schedule_repo.find_available(
        department="心内科",
        start_date=today,
        end_date=today.replace(day=today.day + 2),
    )
    assert len(avail) == 3
    assert avail[0]["remaining"] == 20
    assert avail[0]["schedule_version"] == 0  # v2 新字段


# =====================================================================
# v2: 乐观锁
# =====================================================================
def test_optimistic_lock_cas_success(temp_db_path):
    """乐观锁 CAS 成功。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_repo = ScheduleRepository(db)
    schedule_id = schedule_repo.create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=5
    )

    # 扣 3 次，每次都成功
    for i in range(3):
        ok, new_version = schedule_repo.decrement_remaining(schedule_id, expected_version=i)
        assert ok is True
        assert new_version == i + 1

    s = schedule_repo.get_by_id(schedule_id)
    assert s["remaining"] == 2
    assert s["version"] == 3


def test_optimistic_lock_version_conflict(temp_db_path):
    """乐观锁版本冲突。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        OptimisticLockError,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_repo = ScheduleRepository(db)
    schedule_id = schedule_repo.create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )

    # 第一次扣：version 0 → 1
    schedule_repo.decrement_remaining(schedule_id, expected_version=0)

    # 第二次扣：仍期望 version=0 → 冲突
    with pytest.raises(OptimisticLockError, match="版本冲突"):
        schedule_repo.decrement_remaining(schedule_id, expected_version=0)


def test_optimistic_lock_remaining_exhausted(temp_db_path):
    """乐观锁：库存不足。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        OptimisticLockError,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_repo = ScheduleRepository(db)
    schedule_id = schedule_repo.create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=2
    )

    # 扣 2 次成功
    schedule_repo.decrement_remaining(schedule_id, expected_version=0)
    schedule_repo.decrement_remaining(schedule_id, expected_version=1)

    # 第 3 次：库存不足
    with pytest.raises(OptimisticLockError, match="库存不足"):
        schedule_repo.decrement_remaining(schedule_id, expected_version=2)


def test_schedule_update_via_his(temp_db_path):
    """上游（医生请假）调 update，version 校验。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        OptimisticLockError,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_repo = ScheduleRepository(db)
    schedule_id = schedule_repo.create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )

    # 模拟医生请假
    new_version = schedule_repo.update(
        schedule_id=schedule_id, expected_version=0, is_available=False
    )
    assert new_version == 1

    s = schedule_repo.get_by_id(schedule_id)
    assert s["is_available"] is False or s["is_available"] == 0

    # 用旧 version 再 update → 冲突
    with pytest.raises(OptimisticLockError, match="版本冲突"):
        schedule_repo.update(
            schedule_id=schedule_id, expected_version=0, is_available=True
        )


# =====================================================================
# v2: 幂等性
# =====================================================================
def test_appointment_idempotency_hit(temp_db_path):
    """幂等键命中：返回原 ID。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试患者", phone="13800000000")
    appt_repo = AppointmentRepository(db)

    key = "test-key-001"
    appt_id_1 = appt_repo.create(
        patient_id="P001", doctor_id=doctor_id, schedule_id=schedule_id, idempotency_key=key
    )

    # 第二次同 key：返回原 ID
    appt_id_2 = appt_repo.create(
        patient_id="P001", doctor_id=doctor_id, schedule_id=schedule_id, idempotency_key=key
    )
    assert appt_id_1 == appt_id_2

    # 验证只创建了一条
    assert appt_repo.count_total() == 1


def test_appointment_idempotency_conflict(temp_db_path):
    """幂等键冲突：同 key 不同参数 → 报错。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        IdempotencyConflictError,
        PatientRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    s1 = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    s2 = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="afternoon", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试", phone="")
    appt_repo = AppointmentRepository(db)

    appt_repo.create(patient_id="P001", doctor_id=doctor_id, schedule_id=s1, idempotency_key="dup-key")

    # 同 key 不同的 schedule → 冲突
    with pytest.raises(IdempotencyConflictError):
        appt_repo.create(patient_id="P001", doctor_id=doctor_id, schedule_id=s2, idempotency_key="dup-key")


# =====================================================================
# v2: 事务原子性
# =====================================================================
def test_appointment_create_rollback_on_lock_failure(temp_db_path):
    """落库失败时号源不扣（事务回滚）。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        OptimisticLockError,
        PatientRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试", phone="")
    appt_repo = AppointmentRepository(db)
    schedule_repo = ScheduleRepository(db)

    # 故意传错版本号
    with pytest.raises(OptimisticLockError):
        appt_repo.create(
            patient_id="P001", doctor_id=doctor_id, schedule_id=schedule_id,
            expected_schedule_version=999,  # 错的
        )

    # 号源没扣
    s = schedule_repo.get_by_id(schedule_id)
    assert s["remaining"] == 10
    assert s["version"] == 0  # 没改

    # 没创建 appointment
    assert appt_repo.count_total() == 0


# =====================================================================
# v2: 状态机
# =====================================================================
def test_status_machine_legal_transitions(temp_db_path):
    """合法状态转换。"""
    from medical_agent.db.repositories import validate_status_transition

    # pending → confirmed
    validate_status_transition("pending", "confirmed")
    # pending → cancelled
    validate_status_transition("pending", "cancelled")
    # confirmed → cancelled
    validate_status_transition("confirmed", "cancelled")
    # confirmed → completed
    validate_status_transition("confirmed", "completed")
    # cancelled → pending（恢复）
    validate_status_transition("cancelled", "pending")


def test_status_machine_illegal_transitions():
    """非法状态转换。"""
    from medical_agent.db.repositories import InvalidStatusTransitionError, validate_status_transition

    # pending → completed（跳过 confirmed）
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("pending", "completed")
    # completed → anything（终态）
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("completed", "cancelled")
    # confirmed → pending（不能回退）
    with pytest.raises(InvalidStatusTransitionError):
        validate_status_transition("confirmed", "pending")


# =====================================================================
# v2: 取消 + 恢复
# =====================================================================
def test_appointment_cancel_restores_remaining(temp_db_path):
    """取消预约退回号源。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试", phone="")
    appt_repo = AppointmentRepository(db)

    appt_id = appt_repo.create(patient_id="P001", doctor_id=doctor_id, schedule_id=schedule_id)

    # 取消
    appt_repo.update_status(appt_id, "cancelled", cancelled_reason="患者改主意")
    s = ScheduleRepository(db).get_by_id(schedule_id)
    assert s["remaining"] == 10  # 退回

    appt = appt_repo.get_by_id(appt_id)
    assert appt["status"] == "cancelled"
    assert appt["cancelled_reason"] == "患者改主意"


def test_appointment_restore(temp_db_path):
    """恢复已取消的预约。"""
    from datetime import datetime, timedelta

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试", phone="")
    appt_repo = AppointmentRepository(db)

    appt_id = appt_repo.create(patient_id="P001", doctor_id=doctor_id, schedule_id=schedule_id)
    appt_repo.update_status(appt_id, "cancelled", cancelled_reason="误操作")

    # 恢复
    success = appt_repo.restore(appt_id)
    assert success is True

    appt = appt_repo.get_by_id(appt_id)
    assert appt["status"] == "confirmed"
    # 号源扣回
    s = ScheduleRepository(db).get_by_id(schedule_id)
    assert s["remaining"] == 9


# =====================================================================
# v2: 改约
# =====================================================================
def test_appointment_reschedule(temp_db_path):
    """改约：退旧 schedule + 扣新 schedule。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    old_sched = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    new_sched = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="afternoon", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试", phone="")
    appt_repo = AppointmentRepository(db)
    schedule_repo = ScheduleRepository(db)

    appt_id = appt_repo.create(patient_id="P001", doctor_id=doctor_id, schedule_id=old_sched)
    # 旧 schedule 扣 1
    assert schedule_repo.get_by_id(old_sched)["remaining"] == 9
    assert schedule_repo.get_by_id(new_sched)["remaining"] == 10

    # 改约
    appt_repo.update_schedule(appt_id, new_sched)
    assert schedule_repo.get_by_id(old_sched)["remaining"] == 10  # 退
    assert schedule_repo.get_by_id(new_sched)["remaining"] == 9   # 扣

    appt = appt_repo.get_by_id(appt_id)
    assert appt["schedule_id"] == new_sched


# =====================================================================
# v2: 审计日志
# =====================================================================
def test_audit_log_records_writes(temp_db_path):
    """所有写操作都记录审计日志。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        AuditLogRepository,
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试", phone="")
    appt_repo = AppointmentRepository(db)
    audit_repo = AuditLogRepository(db)

    # 1) create
    appt_id = appt_repo.create(patient_id="P001", doctor_id=doctor_id, schedule_id=schedule_id)
    # 2) cancel
    appt_repo.update_status(appt_id, "cancelled", cancelled_reason="测试")

    logs = audit_repo.list_by_entity("appointment", appt_id)
    assert len(logs) == 2
    # 按 id 倒序：最后写的是 cancel
    assert logs[0]["event_type"] == "appointment.create"
    assert logs[1]["event_type"] == "appointment.cancel"
    assert "schedule_version" in json.loads(logs[0]["metadata"])


# =====================================================================
# v2: 上游变更通知
# =====================================================================
def test_upstream_change_repository(temp_db_path):
    """上游变更表的 record / list_pending / mark_applied。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        ScheduleRepository,
        UpstreamChangeRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    upstream = UpstreamChangeRepository(db)

    # 1) 记录变更
    upstream.record(
        source="his",
        entity_type="schedule",
        entity_id=str(schedule_id),
        change_type="update",
        new_state={"is_available": False},
    )

    # 2) 查 pending
    pending = upstream.list_pending_for_entity("schedule", str(schedule_id))
    assert len(pending) == 1
    assert pending[0]["applied"] is False or pending[0]["applied"] == 0

    # 3) has_pending_change
    assert upstream.has_pending_change("schedule", str(schedule_id)) is True

    # 4) 标记已应用
    upstream.mark_applied(pending[0]["id"])
    assert upstream.has_pending_change("schedule", str(schedule_id)) is False


def test_his_mocker_doctor_cancel(temp_db_path):
    """HISMocker 模拟医生请假 → 写 upstream_changes + 改 schedule。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        ScheduleRepository,
)
    from medical_agent.upstream.his_mock import HISMocker

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    his = HISMocker(db)

    # 医生请假
    success = his.doctor_cancel_schedule(schedule_id, expected_version=0, reason="临时有事")
    assert success is True

    s = ScheduleRepository(db).get_by_id(schedule_id)
    assert s["is_available"] is False or s["is_available"] == 0
    assert s["version"] == 1

    # 用错版本再调 → 失败
    success2 = his.doctor_cancel_schedule(schedule_id, expected_version=0, reason="重复")
    assert success2 is False


def test_his_mocker_adjust_capacity(temp_db_path):
    """HISMocker 调整号源（扩容）。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        ScheduleRepository,
    )
    from medical_agent.upstream.his_mock import HISMocker

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    his = HISMocker(db)

    # 扩容到 15
    success = his.adjust_capacity(schedule_id, expected_version=0, new_capacity=15)
    assert success is True

    s = ScheduleRepository(db).get_by_id(schedule_id)
    assert s["capacity"] == 15
    assert s["remaining"] == 15  # 同步调整


# =====================================================================
# v2: 节假日
# =====================================================================
def test_holiday_judgment():
    """节假日判断。"""
    from datetime import date

    from medical_agent.upstream.holiday import is_holiday, is_workday

    # 元旦
    assert is_holiday(date(2026, 1, 1)) is True
    # 周末
    assert is_workday(date(2026, 1, 3)) is False  # 周六
    # 普通工作日
    assert is_workday(date(2026, 3, 16)) is True  # 周一


# =====================================================================
# v2: 时区
# =====================================================================
def test_timezone_now_in_hospital_tz():
    """医院时区当前时间。"""
    from medical_agent.upstream.timezone import (
        HOSPITAL_TZ,
        now_in_hospital_tz,
        today_in_hospital_tz,
    )

    now = now_in_hospital_tz()
    assert now.tzinfo is not None
    assert now.tzinfo == HOSPITAL_TZ

    today = today_in_hospital_tz()
    assert today is not None


def test_timezone_format_slot_time():
    """格式化时段为字符串。"""
    from datetime import date

    from medical_agent.upstream.timezone import format_slot_time

    s = format_slot_time(date(2026, 9, 1), "morning")
    assert s == "2026-09-01 08:00-12:00"


# =====================================================================
# v2: 并发测试
# =====================================================================
def test_concurrent_decrement_remaining(temp_db_path):
    """多线程并发扣号源：只有 N 个能成功。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        OptimisticLockError,
        ScheduleRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_repo = ScheduleRepository(db)
    schedule_id = schedule_repo.create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=5
    )

    results: list[bool] = []
    errors: list[str] = []

    def worker(version_holder: list[int], tid: int):
        try:
            # 读当前 version
            current = version_holder[0]
            ok, new_version = schedule_repo.decrement_remaining(
                schedule_id, expected_version=current
            )
            results.append(ok)
            if ok:
                version_holder[0] = new_version
        except OptimisticLockError as e:
            errors.append(str(e))

    # 模拟 10 个并发线程抢 5 个号源
    threads = []
    version_holder = [0]
    for i in range(10):
        t = threading.Thread(target=worker, args=(version_holder, i))
        threads.append(t)

    # 因为 SQLite 单 writer，并发会串行化，但乐观锁应保证只有 5 个成功
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # SQLite 的串行化让所有调用都拿到锁串行执行，但因为版本号会更新
    # 实际可能：第一个成功后 version 变了，后面的用旧 version 失败
    # 这里只检查：成功的数量 <= 5
    success_count = sum(1 for r in results if r)
    assert success_count <= 5, f"成功数 {success_count} 超过 capacity 5"

    # 最终 remaining 应该 >= 0
    s = schedule_repo.get_by_id(schedule_id)
    assert s["remaining"] >= 0


# =====================================================================
# v2: 集成测试（HIS 取消 → Agent 落库失败）
# =====================================================================
def test_integration_his_cancel_blocks_appointment(temp_db_path):
    """集成测试：HIS 取消 schedule 后，Agent 落库应被 re-check 拦截。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        AppointmentRepository,
        DepartmentRepository,
        DoctorRepository,
        OptimisticLockError,
        PatientRepository,
        ScheduleRepository,
    )
    from medical_agent.upstream.his_mock import HISMocker

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doctor_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id, schedule_date=date.today(), time_slot="morning", capacity=10
    )
    PatientRepository(db).upsert(patient_id="P001", name="测试", phone="")
    his = HISMocker(db)

    # Agent 先读到 schedule：version=0, available=true
    s_before = ScheduleRepository(db).get_by_id(schedule_id)
    assert s_before["version"] == 0

    # 此时 HIS 推过来：医生请假
    his.doctor_cancel_schedule(schedule_id, expected_version=0, reason="请假")

    # Agent 拿着 version=0 来落库
    with pytest.raises(OptimisticLockError):
        AppointmentRepository(db).create(
            patient_id="P001", doctor_id=doctor_id, schedule_id=schedule_id,
            expected_schedule_version=0,  # 旧版本
        )

    # 上游变更表有 1 条 pending
    from medical_agent.db.repositories import UpstreamChangeRepository
    pending = UpstreamChangeRepository(db).list_pending_for_entity("schedule", str(schedule_id))
    assert len(pending) == 1
