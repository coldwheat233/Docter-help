"""Pydantic 模型测试。"""

import pytest


# =====================================================================
# 枚举
# =====================================================================
def test_intent_type_values():
    from medical_agent.models import IntentType
    assert IntentType.BOOK.value == "book"
    assert IntentType.CONSULT.value == "consult"


# =====================================================================
# 业务模型
# =====================================================================
def test_symptom_report_valid():
    from medical_agent.models import SymptomReport, Severity

    r = SymptomReport(
        symptoms="胃疼", duration="3 天", severity=Severity.MODERATE, department="消化科"
    )
    assert r.symptoms == "胃疼"
    assert r.severity == Severity.MODERATE


def test_symptom_report_department_whitelist():
    from medical_agent.models import SymptomReport

    # 合法
    SymptomReport(department="心内科")
    SymptomReport(department="消化科")
    # 非法
    with pytest.raises(ValueError, match="不在白名单"):
        SymptomReport(department="魔法部")


def test_symptom_report_optional_fields():
    from medical_agent.models import SymptomReport

    r = SymptomReport()  # 全部 None
    assert r.symptoms is None
    assert r.department is None


def test_time_slot_info_required_fields():
    from medical_agent.models import TimeSlotInfo, TimeSlot
    from datetime import date

    s = TimeSlotInfo(
        schedule_id=1,
        doctor_id=2,
        schedule_version=3,
        doctor_name="张三",
        doctor_title="主任医师",
        department="心内科",
        schedule_date=date(2026, 9, 1),
        time_slot=TimeSlot.MORNING,
        start_time="08:00",
        end_time="12:00",
        remaining=10,
    )
    assert s.schedule_id == 1
    assert s.remaining == 10


def test_time_slot_info_validation():
    from medical_agent.models import TimeSlotInfo, TimeSlot
    from datetime import date

    with pytest.raises(ValueError):
        TimeSlotInfo(
            schedule_id=0,  # 必须 >= 1
            doctor_id=1,
            schedule_version=0,
            doctor_name="张三",
            department="心内科",
            schedule_date=date(2026, 9, 1),
            time_slot=TimeSlot.MORNING,
            start_time="08:00",
            end_time="12:00",
            remaining=0,
        )


def test_appointment_result_success_message():
    from medical_agent.models import AppointmentResult, AppointmentStatus

    r = AppointmentResult(
        success=True,
        appointment_id="A20260901ABCD",
        status=AppointmentStatus.CONFIRMED,
    )
    msg = r.to_user_message()
    assert "A20260901ABCD" in msg
    assert "✅" in msg
    # 不应包含内部字段
    assert "patient_id" not in msg
    assert "doctor_id" not in msg
    assert "schedule_id" not in msg


def test_appointment_result_failure_message():
    from medical_agent.models import AppointmentResult

    r = AppointmentResult(
        success=False,
        error_code="APPT_NO_REMAINING",
        error_message="库存不足",
    )
    msg = r.to_user_message()
    assert "❌" in msg
    assert "库存不足" in msg
    # error_code 是技术字段，不应展示
    assert "APPT_NO_REMAINING" not in msg


# =====================================================================
# Tool 输入
# =====================================================================
def test_set_appointment_input_all_optional():
    """set_appointment 所有参数可选（从 state 推断）。"""
    from medical_agent.models import SetAppointmentInput

    inp = SetAppointmentInput()
    assert inp.patient_id == ""
    assert inp.doctor_id == 0


def test_set_appointment_input_severity_validation():
    from medical_agent.models import SetAppointmentInput

    # 合法
    SetAppointmentInput(severity="mild")
    SetAppointmentInput(severity="moderate")
    SetAppointmentInput(severity="severe")
    # 非法
    with pytest.raises(ValueError):
        SetAppointmentInput(severity="极重")


def test_cancel_appointment_input_required_id():
    from medical_agent.models import CancelAppointmentInput

    inp = CancelAppointmentInput(appointment_id="A20260901ABCD")
    assert inp.appointment_id == "A20260901ABCD"

    with pytest.raises(ValueError):
        CancelAppointmentInput(appointment_id="")


# =====================================================================
# State
# =====================================================================
def test_appointment_state_model_defaults():
    from medical_agent.models import AppointmentStateModel

    state = AppointmentStateModel()
    assert state.current_step == "init"
    assert state.messages == []
    assert state.intent is None


def test_appointment_state_model_step_validation():
    from medical_agent.models import AppointmentStateModel

    # 合法
    AppointmentStateModel(current_step="intake")
    AppointmentStateModel(current_step="done")
    # 非法
    with pytest.raises(ValueError, match="current_step 必须是"):
        AppointmentStateModel(current_step="random")


def test_appointment_state_model_intent_enum():
    from medical_agent.models import AppointmentStateModel, IntentType

    state = AppointmentStateModel(intent="book")
    assert state.intent == IntentType.BOOK


def test_appointment_state_model_severity_enum():
    from medical_agent.models import AppointmentStateModel, Severity

    state = AppointmentStateModel(severity="moderate")
    assert state.severity == Severity.MODERATE


def test_appointment_state_model_field_constraints():
    from medical_agent.models import AppointmentStateModel
    from pydantic import ValidationError

    # 症状太长
    with pytest.raises(ValidationError):
        AppointmentStateModel(symptoms="x" * 600)

    # department 非法（不在白名单）
    with pytest.raises(ValidationError):
        AppointmentStateModel(department="外星科")


def test_appointment_state_model_serialization():
    """State 可序列化为 dict（LangGraph 兼容）。"""
    from medical_agent.models import AppointmentStateModel

    state = AppointmentStateModel(patient_id="P001", current_step="intake")
    d = state.model_dump()
    assert d["patient_id"] == "P001"
    assert d["current_step"] == "intake"

    # 反序列化
    state2 = AppointmentStateModel(**d)
    assert state2.patient_id == state.patient_id
