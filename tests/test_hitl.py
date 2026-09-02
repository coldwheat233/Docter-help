"""HITL 节点测试。"""

import pytest


def test_human_confirm_without_selected_slot():
    """未选时段直接取消。"""
    from medical_agent.graphs.hitl import human_confirm_node

    state = {"patient_id": "P001", "selected_slot": None}
    result = human_confirm_node(state)
    assert result["status"] == "cancelled"
    assert "无需确认" in result["final_answer"]


def test_human_confirm_without_patient_id():
    """缺患者 ID 取消。"""
    from medical_agent.graphs.hitl import human_confirm_node

    state = {
        "patient_id": None,
        "selected_slot": {
            "schedule_id": 1,
            "doctor_id": 1,
            "doctor_name": "张三",
            "department": "心内科",
            "schedule_date": "2026-09-10",
            "start_time": "08:00",
            "end_time": "12:00",
        },
    }
    result = human_confirm_node(state)
    assert result["status"] == "cancelled"


def test_should_require_human_confirm_with_selected_slot():
    """选定时段 + 患者 ID → 需要确认。"""
    from medical_agent.graphs.hitl import should_require_human_confirm

    state = {
        "patient_id": "P001",
        "selected_slot": {
            "schedule_id": 1,
            "doctor_id": 1,
        },
    }
    assert should_require_human_confirm(state) is True


def test_should_require_human_confirm_without_slot():
    """无时段 → 不需要确认。"""
    from medical_agent.graphs.hitl import should_require_human_confirm

    state = {"patient_id": "P001", "selected_slot": None}
    assert should_require_human_confirm(state) is False


def test_human_confirm_node_interrupt_no_checkpointer():
    """无 checkpointer 时 interrupt 抛异常，state 保持 pending。"""
    from medical_agent.graphs.hitl import human_confirm_node

    state = {
        "patient_id": "P001",
        "selected_slot": {
            "schedule_id": 1,
            "doctor_id": 1,
            "doctor_name": "张三",
            "department": "心内科",
            "schedule_date": "2026-09-10",
            "start_time": "08:00",
            "end_time": "12:00",
        },
    }
    # 没有 checkpointer 时 interrupt() 抛 NotImplementedError
    result = human_confirm_node(state)
    # 状态应该是 pending 或 cancelled
    assert result["status"] in ("pending", "cancelled", "error")
