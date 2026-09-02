"""RAG stub 知识库测试。"""

import pytest


def test_knowledge_base_not_empty():
    """知识库至少有 5 条。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_BASE

    assert len(KNOWLEDGE_BASE) >= 5


def test_knowledge_base_structure():
    """每条知识有 id/topic/keywords/content。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_BASE

    for kb in KNOWLEDGE_BASE:
        assert "id" in kb
        assert "topic" in kb
        assert "keywords" in kb
        assert "content" in kb
        assert len(kb["keywords"]) > 0
        assert len(kb["content"]) > 20


def test_search_knowledge_gastric_pain():
    """搜"胃疼"返回胃疼知识。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("我胃疼怎么办")
    assert len(results) > 0
    assert results[0]["topic"] == "胃疼"


def test_search_knowledge_hypertension():
    """搜"高血压"返回高血压知识。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("高血压注意什么")
    assert len(results) > 0
    assert "高血压" in results[0]["topic"]


def test_search_knowledge_no_match():
    """搜无关词返回空。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("量子纠缠是什么")
    assert len(results) == 0


def test_search_knowledge_rank_by_score():
    """结果按 score 排序（命中关键词越多越靠前）。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("孩子发烧咳嗽")
    assert len(results) > 0
    # score 应递减
    for i in range(len(results) - 1):
        assert results[i]["score"] >= results[i + 1]["score"]


def test_knowledge_agent_name():
    """knowledge_agent name 唯一。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_AGENT_NAME, build_knowledge_agent

    assert KNOWLEDGE_AGENT_NAME == "knowledge_agent"

    # 用 LLM factory（不实际调用，只验证能 import）
    from medical_agent.llm import get_llm
    get_llm()


def test_supervisor_includes_knowledge_agent():
    """Supervisor 装配包含 knowledge_agent。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_AGENT_NAME
    from medical_agent.graphs.supervisor import build_supervisor_app, SUPERVISOR_PROMPT

    assert KNOWLEDGE_AGENT_NAME in SUPERVISOR_PROMPT


def test_emergency_keywords_in_kb():
    """所有知识条目都包含就医指引关键词。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_BASE

    EMERGENCY_KEYWORDS = ["急诊", "立即就医", "立即就诊", "120"]
    for kb in KNOWLEDGE_BASE:
        assert any(
            keyword in kb["content"]
            for keyword in EMERGENCY_KEYWORDS
        ), f"KB {kb['id']} ({kb['topic']}) 缺就医指引关键词（{EMERGENCY_KEYWORDS}）"
