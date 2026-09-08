"""HITL（Human-in-the-Loop）辅助函数：interrupt 检测与恢复。

v4 说明：
- 真正的 HITL 把门已下沉到 tools/appointment.py 的三个写工具内部（interrupt()）
- 本模块提供调用方（CLI/Web/eval）通用的：
  1) get_pending_interrupt(app, config) — 检测图是否暂停在人工审批点
  2) resume_with_decision(app, config, decision) — 用 Command(resume=...) 恢复
- 保留 human_confirm_node 作为遗留节点（未挂载到任何图，仅测试引用）

LangGraph 语义：
- 工具/节点内 interrupt(payload) → invoke/stream 返回 {"__interrupt__": [Interrupt,...]}
- Command(resume="approve") → 图从断点重跑该工具，interrupt() 返回 resume 值
"""

from __future__ import annotations

import json
import os
from typing import Any

from langgraph.types import Command, interrupt

from medical_agent.state import AppointmentState


# =====================================================================
# 调用方通用辅助（v4 新增）
# =====================================================================
def get_pending_interrupt(app: Any, config: dict) -> Any | None:
    """检测图当前是否暂停在 interrupt 点。

    Returns:
        Interrupt 对象（含 .value 审批 payload）或 None
    """
    try:
        snapshot = app.get_state(config)
    except Exception:
        return None
    for task in getattr(snapshot, "tasks", []) or []:
        interrupts = getattr(task, "interrupts", None) or []
        if interrupts:
            return interrupts[0]
    return None


def resume_with_decision(app: Any, config: dict, decision: str) -> dict:
    """用人工审批决策恢复图执行。

    Args:
        decision: "approve" 或 "reject:原因"（也支持中文"确认"等，
                  判定逻辑见 tools/appointment.py _require_human_approval）

    Returns:
        图继续执行后的最终 state
    """
    return app.invoke(Command(resume=decision), config=config)


def format_interrupt_payload(intr: Any) -> str:
    """把 Interrupt.value 格式化成给人看的审批卡片文本。"""
    payload = getattr(intr, "value", intr)
    if not isinstance(payload, dict):
        return f"待审批操作：{payload}"
    lines = [f"🔔 人工审批请求：{payload.get('action', payload.get('type', '未知操作'))}"]
    for k, v in payload.items():
        if k in ("type", "action", "ask"):
            continue
        if v not in (None, "", 0):
            lines.append(f"  · {k}: {v}")
    lines.append(f"👉 {payload.get('ask', 'approve / reject:原因')}")
    return "\n".join(lines)


# =====================================================================
# 遗留节点（未挂载到图，仅 tests/test_hitl.py 引用）
# =====================================================================
def human_confirm_node(state: AppointmentState) -> dict[str, Any]:
    """HITL 节点：落库前等待人工确认。

    ⚠️ 遗留实现：v4 起 HITL 已下沉到写工具内部，本节点未挂载到任何图。
    保留是为了测试与文档演示 interrupt 节点的写法。

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
        # 调 set_appointment 真落库（bypass 工具内 HITL——本节点自己就是审批点）
        try:
            from medical_agent.tools.appointment import set_appointment

            old = os.environ.get("MEDICAL_HITL_BYPASS")
            os.environ["MEDICAL_HITL_BYPASS"] = "1"
            try:
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
            finally:
                if old is None:
                    os.environ.pop("MEDICAL_HITL_BYPASS", None)
                else:
                    os.environ["MEDICAL_HITL_BYPASS"] = old
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
