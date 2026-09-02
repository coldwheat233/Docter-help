"""路由 Agent：识别用户意图（咨询 / 预约 / 改约 / 取消）。

第 1 周：stub（能 import、name 唯一、可被 Supervisor 装配）
第 2 周：实现 LLM 分类 + 状态写入
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm
from medical_agent.state import AppointmentState, IntentType


ROUTER_AGENT_NAME = "router_agent"
"""Agent 唯一 name，Supervisor 通过这个字符串路由"""


ROUTER_PROMPT = """你是一个医疗预约系统的路由员。
根据用户的最新消息，识别其意图属于以下 4 类之一：
- consult：仅咨询（问症状、问科室、不想预约）
- book：新建预约
- reschedule：改约已有预约
- cancel：取消已有预约

只输出意图分类，不要做其他回复。
"""


def build_router_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造路由 Agent（stub）。

    第 2 周替换为：
    - prompt 改为结构化输出（强制返回 JSON）
    - 写入 state['intent']
    """
    agent = create_react_agent(
        model=get_llm(),
        tools=[],  # 第 2 周填入：query_appointments（查已有预约，用于 cancel/reschedule）
        name=ROUTER_AGENT_NAME,
        prompt=ROUTER_PROMPT,
    )
    return agent


def classify_intent_stub(message: str) -> IntentType:
    """纯规则意图分类（不调 LLM），用于测试和 demo fallback。

    关键词规则：
    - 包含"取消"/"退号"/"不去了" → cancel
    - 包含"改"/"换"/"重新"（变约/改约类） → reschedule
    - 包含"预约"/"挂号"/"想看"/"想约"/"想挂" → book
    - 否则 → consult
    """
    msg = message.lower()
    if any(kw in msg for kw in ["取消", "退号", "退诊", "不去了"]):
        return "cancel"
    # 改约关键词（不能与 cancel 重复）
    if any(kw in msg for kw in ["改约", "改个", "改时间", "改到", "换个时间", "重新约", "改天"]):
        return "reschedule"
    if any(kw in msg for kw in ["预约", "挂号", "挂个号", "想看", "想约", "想挂", "挂个", "挂张"]):
        return "book"
    return "consult"
