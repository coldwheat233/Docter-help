"""4 个子 Agent 工厂。

每个 Agent 是 LangGraph 的 CompiledStateGraph（用 create_react_agent 创建），
名字必须唯一，供 Supervisor/Swarm 路由使用。

本文件只暴露 build_router_agent / build_intake_agent / build_scheduler_agent / build_confirmer_agent
4 个工厂函数。第 2 周会填充具体业务实现。
"""
