"""4 个子 Agent + 1 个知识问答 Agent 工厂。

每个 Agent 是 LangGraph 的 CompiledStateGraph（用 create_react_agent 创建），
名字必须唯一，供 Supervisor/Swarm 路由使用。
"""
