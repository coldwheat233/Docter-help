"""问诊信息收集 Agent：抽取症状、病程、严重程度、推荐科室。

v2 增强：
- 接 LLM 抽取（结构化输出 JSON）
- 注入 list_departments 工具（用科室反查校验）
- 多轮规则：缺字段反问
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm
from medical_agent.tools.scheduling import list_departments


INTAKE_AGENT_NAME = "intake_agent"


INTAKE_PROMPT = """你是医疗预约系统的问诊信息收集员。

目标：从用户主诉中抽取以下 4 个字段
- symptoms（主诉症状）
- duration（病程，如 '3 天'/'1 周'）
- severity（严重程度：mild / moderate / severe）
- department（推荐科室，如 '心内科'/'消化科'）

可用工具：
- list_departments：查所有可用科室（用于校验 department）

多轮规则：
1. 一次只问 1-2 个最关键的字段
2. 已知信息不要重复问
3. 字段全部收齐后输出 JSON：
   ```json
   {"symptoms": "...", "duration": "...", "severity": "mild|moderate|severe", "department": "...", "is_complete": true, "next_question": null}
   ```
4. 字段未齐时输出：
   ```json
   {"symptoms": "已收集的症状或 null", "duration": null, "severity": null, "department": null, "is_complete": false, "next_question": "请问症状持续多久了？"}
   ```
5. 不要下医学诊断，只收集信息
"""


def build_intake_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造问诊 Agent。"""
    return create_react_agent(
        model=get_llm(),
        tools=[list_departments],
        name=INTAKE_AGENT_NAME,
        prompt=INTAKE_PROMPT,
    )
