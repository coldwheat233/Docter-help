"""State 字段测试。"""

import pytest


def test_appointment_state_imports():
    """State 定义能 import。"""
    from medical_agent.state import AppointmentState, IntentType, AppointmentStatus

    assert AppointmentState is not None
    # 类型别名
    assert "consult" in IntentType.__args__
    assert "book" in IntentType.__args__
    assert "pending" in AppointmentStatus.__args__


def test_intent_type_values():
    """IntentType 枚举值正确。"""
    from medical_agent.state import IntentType

    expected = {"consult", "book", "reschedule", "cancel", "unknown"}
    assert set(IntentType.__args__) == expected


def test_appointment_status_values():
    """AppointmentStatus 枚举值正确。"""
    from medical_agent.state import AppointmentStatus

    expected = {"pending", "confirmed", "cancelled", "completed", "no_show"}
    assert set(AppointmentStatus.__args__) == expected


def test_intake_state_imports():
    """intake 内部 State 能 import。"""
    from medical_agent.state import IntakeState

    assert IntakeState is not None
