"""RAG 工具测试。"""

import pytest


def test_search_medical_knowledge_basic():
    """基础检索。"""
    from medical_agent.tools.rag_tool import search_medical_knowledge

    result = search_medical_knowledge.func("胃疼")
    import json
    data = json.loads(result)

    assert data["success"] is True
    assert data["count"] > 0
    assert "胃" in data["results"][0]["topic"]


def test_search_medical_knowledge_top_k():
    """top_k 参数。"""
    from medical_agent.tools.rag_tool import search_medical_knowledge
    import json

    result = search_medical_knowledge.func(query="高血压", top_k=2)
    data = json.loads(result)
    assert data["count"] <= 2


def test_search_medical_knowledge_semantic():
    """同义词召回：'胃痛' → '胃疼'。"""
    from medical_agent.tools.rag_tool import search_medical_knowledge
    import json

    result = search_medical_knowledge.func("胃痛", top_k=3)
    data = json.loads(result)
    # 第一条应是胃疼
    assert "胃" in data["results"][0]["topic"]


def test_search_medical_knowledge_emergency():
    """急诊识别：'胸痛' → '胸痛急诊识别'。"""
    from medical_agent.tools.rag_tool import search_medical_knowledge
    import json

    result = search_medical_knowledge.func("突然胸痛怎么办", top_k=3)
    data = json.loads(result)
    topics = [r["topic"] for r in data["results"]]
    assert any("胸痛" in t for t in topics)


def test_search_medical_knowledge_returned_format():
    """返回 JSON 格式正确。"""
    from medical_agent.tools.rag_tool import search_medical_knowledge
    import json

    result = search_medical_knowledge.func("糖尿病")
    data = json.loads(result)
    # 每条 result 含必要字段
    for r in data["results"]:
        assert "id" in r
        assert "topic" in r
        assert "content" in r
        assert "score" in r


def test_all_rag_tools():
    """工具列表。"""
    from medical_agent.tools.rag_tool import all_rag_tools

    tools = all_rag_tools()
    assert len(tools) == 1
    assert tools[0].name == "search_medical_knowledge"


def test_knowledge_agent_has_rag_tool():
    """knowledge_agent 注入 RAG 工具（不实际 build agent）。"""
    # 直接验证 KNOWLEDGE_PROMPT 包含 RAG 工具说明
    from medical_agent.agents.knowledge import (
        build_knowledge_agent,
        KNOWLEDGE_PROMPT,
    )

    # 直接验证 Prompt 提示使用 RAG 工具
    assert "知识库" in KNOWLEDGE_PROMPT or "检索" in KNOWLEDGE_PROMPT

    # 验证 build 函数能 import（不实际调用）
    assert callable(build_knowledge_agent)
