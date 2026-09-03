"""预约确认 Agent：HITL 把门，落库前必须人工确认。

v2 增强：
- 注入 set_appointment / cancel_appointment / reschedule_appointment 工具
- prompt 强制"先复述详情 → 询问确认 → 才落库"
- 注意：interrupt 真正接入见 graphs/supervisor.py 的 human_confirm_node

v3 增强：
- 注入 query_my_appointments / get_appointment_detail 工具
- 用户问"我有什么预约"也能查
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
from medical_agent.tools.appointment_query import (
    get_appointment_detail,
    query_my_appointments,
)


CONFIRMER_AGENT_NAME = "confirmer_agent"


CONFIRMER_PROMPT = """你是医疗预约系统的确认员。

**核心规则**：你必须**实际调用** `set_appointment` 工具才能落库。仅靠文字描述不会写入数据库！

写操作工具：
- `set_appointment()` - 创建预约（参数可省略，会自动从 state 提取 patient_id/schedule_id/doctor_id）
- `cancel_appointment(appointment_id)` - 取消
- `reschedule_appointment(appointment_id, new_schedule_id)` - 改约
- `restore_appointment(appointment_id)` - 恢复

读操作工具（v3 新增）：
- `query_my_appointments(status="", limit=10)` - 查我的预约（自动从 state 取 patient_id）
- `get_appointment_detail(appointment_id)` - 查单条预约详情

落库流程（必须严格遵守）：
1. 把预约详情复述给用户
2. 用户回复"确认"、"好"、"OK"、"yes"、"approve"等任何肯定词 → **立即调用 set_appointment() 工具**
3. 工具返回后告知用户预约号

查询流程（v3 新增）：
- 用户问"我有什么预约"/"我预约过什么" → 调 `query_my_appointments()`
- 用户问具体某条预约 → 调 `get_appointment_detail(appointment_id)`
- 查完用中文自然语言总结给用户

示例对话：
- 用户："确认" → 你（调 set_appointment()，工具返回 appointment_id A20260901XXXX）→ "✅ 预约成功，预约号 A20260901XXXX"
- 用户："取消" → 你（调 cancel_appointment(id)）→ "已取消"
- 用户："我有什么预约？" → 你（调 query_my_appointments()）→ "您当前有 1 条预约..."

注意：
- 不要在用户没确认前调 set_appointment
- 用户确认后**必须立即调** set_appointment，不要再问问题
- 参数会自动从系统 state 提取，**不要传参或只传 patient_id**
- 查询时不要给用户看 schedule_id 等内部 ID（doctor_name 等展示用）
"""


def build_confirmer_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造确认 Agent。"""
    return create_react_agent(
        model=get_llm(),
        tools=[
            set_appointment,
            cancel_appointment,
            reschedule_appointment,
            restore_appointment,
            # v3: 查询工具
            query_my_appointments,
            get_appointment_detail,
        ],
        name=CONFIRMER_AGENT_NAME,
        prompt=CONFIRMER_PROMPT,
    )
