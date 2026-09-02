"""HITL（Human-in-the-Loop）人工确认节点。

第 2 周：在 supervisor 调度完成后插入 human_confirm_node，
在 set_appointment 落库前用 interrupt() 暂停等人工审批。

第 1 周 stub：纯函数，不真调 interrupt。
"""

from __future__ import annotations

import json
from typing import Any

from langgraph.types import interrupt

from medical_agent.state import AppointmentState


def human_confirm_node(state: AppointmentState) -> dict[str, Any]:
    """HITL 节点：落库前等待人工确认。

    Returns:
        state 更新 dict
    """
    selected = state.get("selected_slot") or {}
    patient_id = state.get("patient_id")

    if not selected or not patient_id:
        return {
            "pending_human_confirm": False,
            "status": "cancelled",
            "final_answer": "未选定时段或缺少患者信息，无需确认",
        }

    # 准备人工审核信息
    confirm_payload = {
        "type": "appointment_confirm",
        "patient_id": patient_id,
        "department": selected.get("department"),
        "doctor": selected.get("doctor_name"),
        "doctor_title": selected.get("doctor_title"),
        "datetime": f"{selected.get('schedule_date')} {selected.get('start_time')}-{selected.get('end_time')}",
        "schedule_id": selected.get("schedule_id"),
        "doctor_id": selected.get("doctor_id"),
        "schedule_version": selected.get("schedule_version", 0),
        "ask": "是否确认预约？输入 'approve' 或 'reject:原因'",
    }

    # 暂停等待人工审批
    try:
        decision = interrupt(confirm_payload)
    except Exception as e:
        # interrupt 在某些场景（如直接 invoke 不带 checkpointer）会抛异常
        return {
            "pending_human_confirm": False,
            "status": "pending",
            "final_answer": f"HITL 中断失败：{e}",
        }

    # 处理决策
    if decision == "approve" or decision == "approve:确认":
        # 调 set_appointment 真落库
        try:
            from medical_agent.tools.appointment import set_appointment

            result_json = set_appointment.func(
                patient_id=patient_id,
                doctor_id=selected["doctor_id"],
                schedule_id=selected["schedule_id"],
                expected_schedule_version=selected.get("schedule_version", 0),
                idempotency_key=f"hitl-{patient_id}-{selected['schedule_id']}",
                symptoms=state.get("symptoms", ""),
                duration=state.get("duration", ""),
                severity=state.get("severity", ""),
            )
            result = json.loads(result_json)

            if result.get("success"):
                return {
                    "pending_human_confirm": False,
                    "status": "confirmed",
                    "appointment_id": result.get("appointment_id"),
                    "final_answer": (
                        f"✅ 预约成功！预约号 {result.get('appointment_id')}\n"
                        f"科室：{selected.get('department')}\n"
                        f"医生：{selected.get('doctor_name')}（{selected.get('doctor_title')}）\n"
                        f"时间：{confirm_payload['datetime']}"
                    ),
                }
            else:
                return {
                    "pending_human_confirm": False,
                    "status": "error",
                    "final_answer": (
                        f"❌ 落库失败：{result.get('error_message', '未知错误')}\n"
                        f"错误码：{result.get('error_code', '')}"
                    ),
                }
        except Exception as e:
            return {
                "pending_human_confirm": False,
                "status": "error",
                "final_answer": f"❌ 落库异常：{e}",
            }
    else:
        # 拒绝
        return {
            "pending_human_confirm": False,
            "status": "cancelled",
            "final_answer": f"已取消：{decision}",
        }


def should_require_human_confirm(state: AppointmentState) -> bool:
    """路由函数：是否需要人工确认。"""
    # 当前规则：所有写操作都需要
    return state.get("selected_slot") is not None and state.get("patient_id") is not None
