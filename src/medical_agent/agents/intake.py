"""问诊信息收集 Agent：抽取症状、病程、严重程度、推荐科室。

第 1 周：stub
第 2 周：实现多轮对话、字段验证、缺字段反问
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm


INTAKE_AGENT_NAME = "intake_agent"


INTAKE_PROMPT = """你是医疗预约系统的问诊信息收集员。

目标：从用户主诉中抽取以下 4 个字段
- symptoms（主诉症状）
- duration（病程，如 '3 天'/'1 周'）
- severity（严重程度：mild / moderate / severe）
- department（推荐科室，如 '心内科'/'消化科'）

多轮规则：
1. 一次只问 1-2 个最关键的字段
2. 已知信息不要重复问
3. 字段全部收齐后回复"已收集完毕"
4. 不要下医学诊断，只收集信息
"""


def build_intake_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造问诊 Agent（stub）。"""
    return create_react_agent(
        model=get_llm(),
        tools=[],  # 第 2 周：tools=[list_departments]
        name=INTAKE_AGENT_NAME,
        prompt=INTAKE_PROMPT,
    )
