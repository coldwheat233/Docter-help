"""多用户并发预约测试（DB 层）。

验证：N 个用户同时抢同一个 capacity=1 的排班，
乐观锁（BEGIN IMMEDIATE + CAS）保证只有 1 个成功，不超卖。
"""

from __future__ import annotations

import threading
from datetime import date, timedelta

import pytest


def _seed_one_slot_schedule(db_path):
    """在临时库造一个只剩 1 个号的排班。返回 schedule_id。"""
    import os

    os.environ["DB_PATH"] = str(db_path)
    from medical_agent.config import reload_settings

    reload_settings()
    from medical_agent.db.database import close_db, get_db, init_db

    close_db()  # 清掉单例连接，确保指到本用例的临时库
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
    )

    init_db()
    db = get_db()
    DepartmentRepository(db).create("TEST_CONC", "并发测试科", "压测专用")
    doctor_id = DoctorRepository(db).create("压测医生", "并发测试科")
    schedule_id = ScheduleRepository(db).create(
        doctor_id=doctor_id,
        schedule_date=date.today() + timedelta(days=1),
        time_slot="morning",
        capacity=1,  # 只有 1 个号
    )
    # 10 个患者
    for i in range(10):
        PatientRepository(db).upsert(f"PC{i:03d}", f"压测患者{i}")
    db.commit()
    return schedule_id


def test_concurrent_booking_no_oversell(tmp_path):
    """10 线程抢 1 个号：恰好 1 个成功，remaining 归零，不超卖。"""
    db_path = tmp_path / "conc.db"
    schedule_id = _seed_one_slot_schedule(db_path)

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import AppointmentRepository

    results: list[str | Exception] = [None] * 10  # type: ignore
    barrier = threading.Barrier(10)  # 尽量同时起跑

    def worker(i: int):
        barrier.wait(timeout=5)
        try:
            appt_id = AppointmentRepository(get_db()).create(
                patient_id=f"PC{i:03d}",
                doctor_id=1,
                schedule_id=schedule_id,
                idempotency_key=f"conc-{i}",
            )
            results[i] = appt_id
        except Exception as e:
            results[i] = e

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    successes = [r for r in results if isinstance(r, str)]
    failures = [r for r in results if isinstance(r, Exception)]

    assert len(successes) == 1, f"应恰好 1 个成功，实际 {len(successes)}：{results}"
    assert len(failures) == 9

    # DB 终态：remaining=0， appointments 只有 1 条
    db = get_db()
    row = db.execute("SELECT remaining FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    assert row["remaining"] == 0
    count = db.execute(
        "SELECT COUNT(*) c FROM appointments WHERE schedule_id = ?", (schedule_id,)
    ).fetchone()["c"]
    assert count == 1


def test_idempotent_retry_same_key(tmp_path):
    """同一幂等键重试：返回同一个 appointment_id，不产生重复记录。"""
    db_path = tmp_path / "idem.db"
    schedule_id = _seed_one_slot_schedule(db_path)

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import AppointmentRepository

    repo = AppointmentRepository(get_db())
    a1 = repo.create(
        patient_id="PC000", doctor_id=1, schedule_id=schedule_id, idempotency_key="retry-1"
    )
    a2 = repo.create(
        patient_id="PC000", doctor_id=1, schedule_id=schedule_id, idempotency_key="retry-1"
    )
    assert a1 == a2
    count = get_db().execute(
        "SELECT COUNT(*) c FROM appointments WHERE schedule_id = ?", (schedule_id,)
    ).fetchone()["c"]
    assert count == 1
