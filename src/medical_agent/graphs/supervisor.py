"""Supervisor 图装配：4 个子 Agent + knowledge_agent + Supervisor 路由。

参考实现：pareshraut/Langgraph-agents 的 src/doc-agent/graph.py
API 文档：https://github.com/langchain-ai/langgraph-supervisor-py

第 1 周：能编译、能 invoke（用 stub Agent 跑通）
第 2 周：填充业务逻辑
"""

from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver
from langgraph_supervisor import create_supervisor

from medical_agent.agents.confirmer import build_confirmer_agent, CONFIRMER_AGENT_NAME
from medical_agent.agents.intake import build_intake_agent, INTAKE_AGENT_NAME
from medical_agent.agents.knowledge import build_knowledge_agent, KNOWLEDGE_AGENT_NAME
from medical_agent.agents.router import build_router_agent, ROUTER_AGENT_NAME
from medical_agent.agents.scheduler import build_scheduler_agent, SCHEDULER_AGENT_NAME
from medical_agent.llm import get_llm
from medical_agent.state import AppointmentState


SUPERVISOR_NAME = "supervisor"

SUPERVISOR_PROMPT = f"""你是医疗预约系统的调度中心（Supervisor）。
你的工作是接收用户消息后，决定交给哪个子 Agent 处理。

子 Agent 分工：
- {ROUTER_AGENT_NAME}：识别用户意图（咨询 / 预约 / 改约 / 取消）
- {INTAKE_AGENT_NAME}：问诊信息收集（症状、病程、严重程度、科室）
- {SCHEDULER_AGENT_NAME}：时间推荐（根据排班表匹配可用时段）
- {CONFIRMER_AGENT_NAME}：预约确认（落库前人工审核）
- {KNOWLEDGE_AGENT_NAME}：医学知识问答（症状护理、急诊指引、科室建议）

路由规则（按顺序判断）：
1. 用户问症状/护理/急诊/非挂号类问题 → {KNOWLEDGE_AGENT_NAME}
2. 用户首条消息 / 意图不明 → {ROUTER_AGENT_NAME}
3. 已识别为"预约"且信息未全 → {INTAKE_AGENT_NAME}
4. 信息已全，需要看时间 → {SCHEDULER_AGENT_NAME}
5. 用户已选定时段 → {CONFIRMER_AGENT_NAME}
6. 用户问咨询类问题 → {KNOWLEDGE_AGENT_NAME}（如未走通上面）

约束：
- 任何"写操作"（创建/取消/改约）必须经过 {CONFIRMER_AGENT_NAME} 的人工确认
- 不要重复问已收集的信息
- 同一轮只路由一个 Agent
"""


def build_supervisor_app(checkpointer: InMemorySaver | None = None):
    """构造 Supervisor 应用。

    Args:
        checkpointer: 默认 InMemorySaver；测试时可换别的 saver

    Returns:
        编译后的 LangGraph 应用
    """
    # 1. 构造 4 个子 Agent + 1 知识 Agent
    agents = [
        build_router_agent(),
        build_intake_agent(),
        build_scheduler_agent(),
        build_confirmer_agent(),
        build_knowledge_agent(),
    ]

    # 2. 装配 Supervisor
    workflow = create_supervisor(
        agents=agents,
        model=get_llm(),
        prompt=SUPERVISOR_PROMPT,
        output_mode="last_message",  # 子 Agent 只回最后一条，省 token
        add_handoff_messages=True,   # 自动插入转交消息
        supervisor_name=SUPERVISOR_NAME,
    )

    # 3. 编译（必须配 checkpointer，因为 HITL interrupt 需要）
    app = workflow.compile(checkpointer=checkpointer or InMemorySaver())
    return app


def run_demo_query(query: str, thread_id: str = "demo-thread-001") -> dict:
    """运行单条 query 的便捷函数。"""
    app = build_supervisor_app()
    config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(
        {"messages": [{"role": "user", "content": query}]},
        config=config,
    )
    return result


if __name__ == "__main__":
    print("Supervisor 图已构造完毕。")
    print(f"  子 Agent: {[ROUTER_AGENT_NAME, INTAKE_AGENT_NAME, SCHEDULER_AGENT_NAME, CONFIRMER_AGENT_NAME, KNOWLEDGE_AGENT_NAME]}")
    print(f"  Supervisor: {SUPERVISOR_NAME}")
    print()
    print("用法：python demos/03_medical_appointment_demo.py")
