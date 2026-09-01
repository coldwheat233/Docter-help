"""Swarm 图装配：4 个子 Agent + handoff 互转（去中心化）。

仅作 Supervisor 的对比实验，**不是主交付物**。

Swarm 特点：
- 无中心 Supervisor
- 每个 Agent 持 handoff 工具，主动决定把控制权交给谁
- 必须配 checkpointer（记 default_active_agent）
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph_swarm import create_handoff_tool, create_swarm

from medical_agent.agents.confirmer import build_confirmer_agent, CONFIRMER_AGENT_NAME
from medical_agent.agents.intake import build_intake_agent, INTAKE_AGENT_NAME
from medical_agent.agents.router import build_router_agent, ROUTER_AGENT_NAME
from medical_agent.agents.scheduler import build_scheduler_agent, SCHEDULER_AGENT_NAME
from medical_agent.llm import get_llm


def build_swarm_app(checkpointer: InMemorySaver | None = None):
    """构造 Swarm 应用。

    Swarm 模式下，每个子 Agent 持有指向其他 Agent 的 handoff 工具。
    路由逻辑写在每个 Agent 的 prompt + handoff 工具里，没有中心调度。
    """
    # 1. 定义 handoff 工具
    handoff_to_intake = create_handoff_tool(
        agent_name=INTAKE_AGENT_NAME,
        description="转交问诊信息收集员处理（症状/病程/严重程度/科室未收齐时使用）",
    )
    handoff_to_scheduler = create_handoff_tool(
        agent_name=SCHEDULER_AGENT_NAME,
        description="转交时间推荐员处理（信息已收齐，需要看可用时段时使用）",
    )
    handoff_to_confirmer = create_handoff_tool(
        agent_name=CONFIRMER_AGENT_NAME,
        description="转交确认员处理（用户已选定时段，需要人工确认时使用）",
    )
    handoff_to_router = create_handoff_tool(
        agent_name=ROUTER_AGENT_NAME,
        description="转回路由员重新识别意图",
    )

    # 2. 每个 Agent 装配 handoff 工具
    # 注意：这里直接 build_xxx_agent() 已经创建好了，但 Swarm 要求每个 Agent 自己持有 handoff tool
    # 第 1 周 stub：build_*_agent() 没注入 handoff，这里用简化版（直接复用 ReAct agent 不带 handoff）
    # 第 2 周会重写：每个 agent 自己持 build_react_agent 重新构造 + handoff 工具
    from langgraph.prebuilt import create_react_agent

    from medical_agent.agents.confirmer import CONFIRMER_PROMPT
    from medical_agent.agents.intake import INTAKE_PROMPT
    from medical_agent.agents.router import ROUTER_PROMPT
    from medical_agent.agents.scheduler import SCHEDULER_PROMPT

    router_agent = create_react_agent(
        model=get_llm(),
        tools=[handoff_to_intake],
        name=ROUTER_AGENT_NAME,
        prompt=ROUTER_PROMPT,
    )
    intake_agent = create_react_agent(
        model=get_llm(),
        tools=[handoff_to_scheduler, handoff_to_router],
        name=INTAKE_AGENT_NAME,
        prompt=INTAKE_PROMPT,
    )
    scheduler_agent = create_react_agent(
        model=get_llm(),
        tools=[handoff_to_confirmer, handoff_to_intake],
        name=SCHEDULER_AGENT_NAME,
        prompt=SCHEDULER_PROMPT,
    )
    confirmer_agent = create_react_agent(
        model=get_llm(),
        tools=[handoff_to_router, handoff_to_scheduler],
        name=CONFIRMER_AGENT_NAME,
        prompt=CONFIRMER_PROMPT,
    )

    # 3. 装配 Swarm
    workflow = create_swarm(
        agents=[router_agent, intake_agent, scheduler_agent, confirmer_agent],
        default_active_agent=ROUTER_AGENT_NAME,
    )

    # 4. 编译（必须配 checkpointer）
    app = workflow.compile(checkpointer=checkpointer or InMemorySaver())
    return app


if __name__ == "__main__":
    print("Swarm 图已构造完毕（对比实验用）。")
    print(f"  子 Agent: {[ROUTER_AGENT_NAME, INTAKE_AGENT_NAME, SCHEDULER_AGENT_NAME, CONFIRMER_AGENT_NAME]}")
    print("  入口 Agent: router_agent（default_active_agent）")
