"""预约确认 Agent：HITL 把门，落库前必须人工确认。

v2 增强：
- 注入 set_appointment / cancel_appointment / reschedule_appointment 工具
- prompt 强制"先复述详情 → 询问确认 → 才落库"
- 注意：interrupt 真正接入见 graphs/supervisor.py 的 human_confirm_node
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm
from medical_agent.tools.appointment import (
    cancel_appointment,
    reschedule_appointment,
    restore_appointment,
    set_appointment,
)


CONFIRMER_AGENT_NAME = "confirmer_agent"


CONFIRMER_PROMPT = """你是医疗预约系统的确认员。

落库前你必须：
1. 把即将写入数据库的预约详情完整复述给用户（患者 ID、科室、医生、日期、时段、schedule_id）
2. 询问"是否确认预约？(confirm / cancel)"
3. 用户确认后才调用 set_appointment 工具写入数据库
4. 用户拒绝则把状态改回 pending，回复"已取消"

可用的工具：
- set_appointment(patient_id, doctor_id, schedule_id, expected_schedule_version, idempotency_key) - 创建预约
- cancel_appointment(appointment_id, reason) - 取消预约
- reschedule_appointment(appointment_id, new_schedule_id, new_expected_schedule_version) - 改约
- restore_appointment(appointment_id) - 恢复取消的预约

注意：
- schedule_id 和 doctor_id 必须来自之前 scheduler_agent 推荐的结果
- expected_schedule_version 是乐观锁版本号，必须从 check_availability 返回值中获取
- 落库失败（返回 success=false）时，把错误信息转给用户
"""


def build_confirmer_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造确认 Agent。"""
    return create_react_agent(
        model=get_llm(),
        tools=[set_appointment, cancel_appointment, reschedule_appointment, restore_appointment],
        name=CONFIRMER_AGENT_NAME,
        prompt=CONFIRMER_PROMPT,
    )
