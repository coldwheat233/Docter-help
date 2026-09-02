"""时间推荐 Agent：根据用户偏好 + 排班表匹配可用时段。

v2 增强：
- 注入 check_availability + list_doctors + list_departments 工具
- 引导 LLM 排序推荐
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm
from medical_agent.tools.scheduling import (
    check_availability,
    list_departments,
    list_doctors,
)


SCHEDULER_AGENT_NAME = "scheduler_agent"


SCHEDULER_PROMPT = """你是医疗预约系统的时间推荐员。

可用工具：
- list_departments：查所有科室
- list_doctors(department)：查某科室医生
- check_availability(department, start_date, end_date, time_slot)：查可用排班

任务：根据用户偏好（日期/时段）和医生排班表，推荐 3-5 个可选时段。

规则：
1. 优先匹配用户 preferred_date 和 preferred_time_slot
2. 没有偏好时推荐最近的 3 天内的 5 个时段
3. 按时段排序：上午 > 下午 > 晚班
4. 输出格式：每行一个时段，格式 "[YYYY-MM-DD HH:MM] 医生名 - 科室"
5. 至少给 3 个候选，让用户选
6. 如果 0 候选，明确告诉用户"该科室暂无可约时段"并建议改期
"""


def build_scheduler_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造时间推荐 Agent。"""
    return create_react_agent(
        model=get_llm(),
        tools=[check_availability, list_doctors, list_departments],
        name=SCHEDULER_AGENT_NAME,
        prompt=SCHEDULER_PROMPT,
    )
