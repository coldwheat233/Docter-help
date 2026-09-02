"""路由 Agent：识别用户意图（咨询 / 预约 / 改约 / 取消）。

v2 增强：
- 接 LLM 分类（结构化输出 JSON）
- fallback 规则分类（classify_intent_stub）当 LLM 不可用
- 工具预留：query_appointments（查已有预约）
"""

from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from medical_agent.llm import get_llm
from medical_agent.state import AppointmentState, IntentType


ROUTER_AGENT_NAME = "router_agent"
"""Agent 唯一 name，Supervisor 通过这个字符串路由"""


ROUTER_PROMPT = """你是一个医疗预约系统的路由员。
你的任务：根据用户的最新消息，识别其意图属于以下 4 类之一：
- consult：仅咨询（问症状、问科室、不想预约）
- book：新建预约
- reschedule：改约已有预约
- cancel：取消已有预约

**输出格式**：必须以 JSON 格式回复，便于系统解析：
```json
{"intent": "book|reschedule|cancel|consult", "confidence": 0.0-1.0, "reason": "简短原因"}
```

不要输出其他内容。如果用户意图不明，输出 consult + 低 confidence。
"""


def build_router_agent() -> "CompiledStateGraph":  # noqa: F821
    """构造路由 Agent。

    v2: 注入查询工具（占位）。prompt 强制 JSON 输出。
    """
    from medical_agent.tools.scheduling import list_departments

    return create_react_agent(
        model=get_llm(),
        tools=[],  # 暂不注入 list_departments，避免循环依赖；如需科室列表可加
        name=ROUTER_AGENT_NAME,
        prompt=ROUTER_PROMPT,
    )


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


def parse_intent_from_text(text: str) -> IntentType | None:
    """从 LLM 输出解析 intent（JSON 或纯文本）。"""
    import json
    import re

    if not text:
        return None

    # 尝试解析 JSON
    try:
        # 找 JSON 块
        match = re.search(r"\{[^{}]*\"intent\"[^{}]*\}", text)
        if match:
            data = json.loads(match.group(0))
            intent = data.get("intent", "").lower().strip()
            if intent in ("consult", "book", "reschedule", "cancel"):
                return intent  # type: ignore
    except (json.JSONDecodeError, AttributeError):
        pass

    # Fallback: 关键词匹配
    return classify_intent_stub(text)
