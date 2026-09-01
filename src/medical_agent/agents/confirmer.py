"""预约确认 Agent：HITL 把门，落库前必须人工确认。

第 1 周：stub
第 2 周：实现 interrupt() 暂停 + 人工审批 + 落库
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm


CONFIRMER_AGENT_NAME = "confirmer_agent"


CONFIRMER_PROMPT = """你是医疗预约系统的确认员。

落库前你必须：
1. 把即将写入数据库的预约详情完整复述给用户（患者 ID、科室、医生、日期、时段）
2. 询问"是否确认预约？(confirm / cancel)"
3. 用户确认后才调用 set_appointment 工具写入数据库
4. 用户拒绝则把状态改回 pending，回复"已取消"
"""


def build_confirmer_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造确认 Agent（stub）。"""
    return create_react_agent(
        model=get_llm(),
        tools=[],  # 第 2 周：tools=[set_appointment, cancel_appointment]
        name=CONFIRMER_AGENT_NAME,
        prompt=CONFIRMER_PROMPT,
    )
