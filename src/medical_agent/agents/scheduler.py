"""时间推荐 Agent：根据用户偏好 + 排班表匹配可用时段。

第 1 周：stub
第 2 周：实现时段推荐算法 + 排序 + 过滤
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm


SCHEDULER_AGENT_NAME = "scheduler_agent"


SCHEDULER_PROMPT = """你是医疗预约系统的时间推荐员。

任务：根据用户偏好（日期/时段）和医生排班表，推荐 3-5 个可选时段。

规则：
1. 优先匹配用户 preferred_date 和 preferred_time_slot
2. 没有偏好时推荐最近的 3 天内的 5 个时段
3. 按时段排序：上午 > 下午 > 晚班
4. 输出格式：每行一个时段，格式 "[YYYY-MM-DD HH:MM] 医生名 - 科室"
5. 至少给 3 个候选，让用户选
"""


def build_scheduler_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造时间推荐 Agent（stub）。"""
    return create_react_agent(
        model=get_llm(),
        tools=[],  # 第 2 周：tools=[check_availability, list_doctors, list_departments]
        name=SCHEDULER_AGENT_NAME,
        prompt=SCHEDULER_PROMPT,
    )
