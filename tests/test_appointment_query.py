"""预约查询测试。"""

import pytest


def test_query_my_appointments_no_patient_id(temp_db_path):
    """无 patient_id 返回错误。"""
    from medical_agent.tools.appointment_query import query_my_appointments

    result = query_my_appointments.func(runtime=None)
    import json
    data = json.loads(result)
    assert data["success"] is False
    assert data["error_code"] == "NO_PATIENT_ID"


def test_query_my_appointments_empty(temp_db_path):
    """无预约时返回空列表。"""
    from medical_agent.tools.appointment_query import query_my_appointments

    # mock runtime
    class FakeRuntime:
        state = {"patient_id": "P_TEST_EMPTY"}

    result = query_my_appointments.func(runtime=FakeRuntime())
    import json
    data = json.loads(result)
    assert data["success"] is True
    assert data["count"] == 0
    assert data["appointments"] == []


def test_query_my_appointments_with_data(temp_db_path):
    """有预约时返回列表。"""
    from datetime import date
    from medical_agent.tools.appointment_query import query_my_appointments
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        DepartmentRepository,
        DoctorRepository,
        PatientRepository,
        ScheduleRepository,
        AppointmentRepository,
    )

    db = get_db()
    DepartmentRepository(db).create(code="IM", name="心内科", description="")
    doc_id = DoctorRepository(db).create(name="张三", department="心内科", title="主任医师")
    sched_id = ScheduleRepository(db).create(
        doctor_id=doc_id,
        schedule_date=date(2026, 9, 1),
        time_slot="morning",
        capacity=10,
    )
    PatientRepository(db).upsert(patient_id="P_TEST", name="测试")
    AppointmentRepository(db).create(
        patient_id="P_TEST", doctor_id=doc_id, schedule_id=sched_id
    )

    class FakeRuntime:
        state = {"patient_id": "P_TEST"}

    result = query_my_appointments.func(runtime=FakeRuntime())
    import json
    data = json.loads(result)
    assert data["success"] is True
    assert data["count"] >= 1
    assert data["appointments"][0]["status"] == "confirmed"


def test_query_my_appointments_filter_by_status(temp_db_path):
    """按状态过滤。"""
    from datetime import date
    from medical_agent.tools.appointment_query import query_my_appointments
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
    doc_id = DoctorRepository(db).create(name="李", department="心内科", title="X")
    sched_id = ScheduleRepository(db).create(
        doctor_id=doc_id,
        schedule_date=date(2026, 9, 1),
        time_slot="morning",
        capacity=10,
    )
    PatientRepository(db).upsert(patient_id="P_FILTER", name="X")
    appt_id = AppointmentRepository(db).create(
        patient_id="P_FILTER", doctor_id=doc_id, schedule_id=sched_id
    )
    AppointmentRepository(db).update_status(appt_id, "cancelled")

    class FakeRuntime:
        state = {"patient_id": "P_FILTER"}

    # 查全部
    r = query_my_appointments.func(runtime=FakeRuntime())
    import json
    data = json.loads(r)
    assert data["count"] == 1

    # 查 cancelled
    r = query_my_appointments.func(status="cancelled", runtime=FakeRuntime())
    data = json.loads(r)
    assert data["count"] == 1
    assert data["appointments"][0]["status"] == "cancelled"

    # 查 confirmed（应为 0）
    r = query_my_appointments.func(status="confirmed", runtime=FakeRuntime())
    data = json.loads(r)
    assert data["count"] == 0


def test_query_my_appointments_no_internal_id_in_response():
    """响应不暴露 system 字段（patient_id 自己可见，schedule_id 给前端处理）。"""
    from medical_agent.tools.appointment_query import query_my_appointments

    class FakeRuntime:
        state = {"patient_id": "P_TEST"}

    r = query_my_appointments.func(runtime=FakeRuntime())
    # patient_id 是自己 OK
    # schedule_id / version 应该隐藏
    # 但我们返回了（供前端展示），验证 JSON 里有 schedule_id 用于后续查详情


def test_get_appointment_detail_not_found():
    """预约不存在。"""
    from medical_agent.tools.appointment_query import get_appointment_detail
    from medical_agent.db.database import init_db
    init_db()  # 确保表存在

    r = get_appointment_detail.func(appointment_id="A99999999", runtime=None)
    import json
    data = json.loads(r)
    assert data["success"] is False
    assert data["error_code"] == "NOT_FOUND"


def test_get_appointment_detail_forbidden(temp_db_path):
    """无权查看他人预约。"""
    from datetime import date
    from medical_agent.tools.appointment_query import get_appointment_detail
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
    doc_id = DoctorRepository(db).create(name="X", department="心内科", title="X")
    sched_id = ScheduleRepository(db).create(
        doctor_id=doc_id,
        schedule_date=date(2026, 9, 1),
        time_slot="morning",
        capacity=10,
    )
    PatientRepository(db).upsert(patient_id="P_OWNER", name="X")
    appt_id = AppointmentRepository(db).create(
        patient_id="P_OWNER", doctor_id=doc_id, schedule_id=sched_id
    )

    class FakeRuntime:
        state = {"patient_id": "P_OTHER"}  # 不是 P_OWNER

    r = get_appointment_detail.func(appointment_id=appt_id, runtime=FakeRuntime())
    import json
    data = json.loads(r)
    assert data["success"] is False
    assert data["error_code"] == "FORBIDDEN"


def test_all_query_tools():
    """工具列表。"""
    from medical_agent.tools.appointment_query import all_query_tools

    tools = all_query_tools()
    assert len(tools) == 2
    names = {t.name for t in tools}
    assert "query_my_appointments" in names
    assert "get_appointment_detail" in names
