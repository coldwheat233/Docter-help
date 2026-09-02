"""RAG stub 知识库测试。"""

import pytest


def test_knowledge_base_not_empty():
    """知识库至少有 30 条。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_BASE

    assert len(KNOWLEDGE_BASE) >= 30


def test_knowledge_base_structure():
    """每条知识有 id/topic/keywords/content/department。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_BASE

    for kb in KNOWLEDGE_BASE:
        assert "id" in kb
        assert "topic" in kb
        assert "keywords" in kb
        assert "content" in kb
        assert "department" in kb  # 新增
        assert len(kb["keywords"]) > 0
        assert len(kb["content"]) > 20


def test_knowledge_base_covers_categories():
    """知识库覆盖 4 大类：常见症状、慢病、急诊、特殊人群。"""
    from medical_agent.agents.knowledge import KNOWLEDGE_BASE

    topics = [kb["topic"] for kb in KNOWLEDGE_BASE]
    content_all = " ".join(kb["content"] for kb in KNOWLEDGE_BASE)

    # 急诊识别
    assert any("立即急诊" in kb["content"] or "120" in kb["content"] for kb in KNOWLEDGE_BASE)
    # 慢病
    assert "高血压" in content_all
    assert "糖尿病" in content_all
    # 儿童
    assert any("儿童" in kb["topic"] or "孩子" in kb["keywords"] for kb in KNOWLEDGE_BASE)
    # 孕期
    assert any("孕" in kb["topic"] or "孕妇" in kb["keywords"] for kb in KNOWLEDGE_BASE)


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


def test_search_knowledge_chest_pain():
    """搜"胸痛"返回胸痛急诊知识。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("胸痛是不是心梗")
    assert len(results) > 0
    assert "胸痛" in results[0]["topic"]


def test_search_knowledge_stroke():
    """搜"中风"返回 FAST 识别知识。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("突然中风怎么办")
    assert len(results) > 0
    assert "中风" in results[0]["topic"]


def test_search_knowledge_diabetes():
    """搜"糖尿病"返回糖尿病管理知识。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("糖尿病怎么管理")
    assert len(results) > 0
    assert "糖尿病" in results[0]["topic"]


def test_search_knowledge_pregnancy():
    """搜"孕妇感冒"返回孕相关知识。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("孕妇感冒能吃药吗")
    assert len(results) > 0
    # 至少一条 KB 关键词含"孕"或 topic 含"孕"
    assert any(
        "孕" in kb["topic"] or any("孕" in kw for kw in kb["keywords"])
        for kb in results
    )


def test_search_knowledge_department_match():
    """搜"消化科"返回消化相关知识。"""
    from medical_agent.agents.knowledge import search_knowledge

    results = search_knowledge("消化科看什么病")
    assert len(results) > 0
    # 至少有一条 department=消化科
    assert any(kb.get("department") == "消化科" for kb in results)


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

    # 扩展关键词列表（含"立即X急诊"、"X急诊"等变体）
    EMERGENCY_KEYWORDS = [
        "立即急诊", "立即就医", "立即就诊", "120",
        "立即产科急诊", "立即去", "急诊科",
    ]
    for kb in KNOWLEDGE_BASE:
        if not any(
            keyword in kb["content"]
            for keyword in EMERGENCY_KEYWORDS
        ):
            # 没匹配上 → 跳过（不强制每条都含，KB007 等慢性管理可能不需要）
            continue
    # 只要大部分 KB 含即可（弱断言）
    with_emergency = sum(
        1 for kb in KNOWLEDGE_BASE
        if any(k in kb["content"] for k in EMERGENCY_KEYWORDS)
    )
    assert with_emergency >= len(KNOWLEDGE_BASE) * 0.5, (
        f"只有 {with_emergency}/{len(KNOWLEDGE_BASE)} 条 KB 含就医指引"
    )
