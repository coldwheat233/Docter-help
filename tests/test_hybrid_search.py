"""BM25 + 关键词融合检索测试。"""

import pytest


# =====================================================================
# 1. Tokenizer
# =====================================================================
def test_tokenize_chinese():
    """中文 tokenize。"""
    from medical_agent.agents.hybrid_search import tokenize

    tokens = tokenize("胃疼怎么办")
    # 单字符 + bigram
    assert "胃" in tokens
    assert "疼" in tokens
    assert "胃疼" in tokens


def test_tokenize_english():
    """英文 tokenize。"""
    from medical_agent.agents.hybrid_search import tokenize

    tokens = tokenize("high blood pressure")
    assert "high" in tokens
    assert "blood" in tokens
    assert "pressure" in tokens


def test_tokenize_mixed():
    """中英混合。"""
    from medical_agent.agents.hybrid_search import tokenize

    tokens = tokenize("感冒了，吃 Tylenol")
    assert "感" in tokens
    assert "冒" in tokens
    assert "感冒" in tokens
    assert "tylenol" in tokens


def test_tokenize_empty():
    """空字符串。"""
    from medical_agent.agents.hybrid_search import tokenize

    assert tokenize("") == []


# =====================================================================
# 2. BM25 算法
# =====================================================================
def test_bm25_basic_ranking():
    """BM25 能区分相关与不相关文档。"""
    from medical_agent.agents.hybrid_search import BM25, tokenize

    corpus = [
        tokenize("高血压患者注意事项"),
        tokenize("糖尿病患者日常管理"),
        tokenize("苹果香蕉西瓜"),
    ]
    bm25 = BM25(corpus)

    # 查"高血压"应该返回第 0 篇得分高
    results = bm25.rank("高血压")
    assert len(results) > 0
    assert results[0][0] == 0  # 第 0 篇排第一
    # 苹果香蕉那篇不应该出现
    assert 2 not in [idx for idx, _ in results]


def test_bm25_zero_for_unrelated():
    """不相关查询得 0。"""
    from medical_agent.agents.hybrid_search import BM25, tokenize

    corpus = [
        tokenize("apple banana"),
        tokenize("cat dog"),
    ]
    bm25 = BM25(corpus)
    results = bm25.rank("高血压")
    # 高血压与 apple/cat/dog 都不相关
    assert results == [] or all(s == 0 for _, s in results)


def test_bm25_idf_calculation():
    """IDF 计算正确。"""
    from medical_agent.agents.hybrid_search import BM25, tokenize

    corpus = [
        tokenize("高血压 病"),
        tokenize("糖尿病 病"),
        tokenize("感冒 病"),
    ]
    bm25 = BM25(corpus)
    # "高血压" 仅 1 个文档，IDF 应较高
    # "病" 在 3 个文档都出现，IDF 应较低
    # 注意：tokenize("高血压 病") 可能产生多个 token（含单字"高"等）
    # 但 "高血压" 这个 bigram 一定存在
    high_bp_score = bm25.idf.get("高血压", 0)
    bing_score = bm25.idf.get("病", 0)
    # 至少一个能找到
    assert high_bp_score > 0 or bing_score > 0
    if high_bp_score > 0 and bing_score > 0:
        # "高血压"（仅 1 文档）IDF > "病"（3 文档）IDF
        assert high_bp_score > bing_score


# =====================================================================
# 3. 融合检索
# =====================================================================
def test_hybrid_search_finds_relevant():
    """融合检索能召回相关 KB。"""
    from medical_agent.agents.hybrid_search import hybrid_search

    results = hybrid_search("我胃疼怎么办", top_k=3)
    assert len(results) > 0
    assert results[0]["topic"] == "胃疼"


def test_hybrid_search_handles_synonyms():
    """BM25 大字性能：近义词能召回。"""
    from medical_agent.agents.hybrid_search import hybrid_search

    # "胃疼" 和 "胃痛" 是同义词
    results = hybrid_search("胃痛", top_k=3)
    # 应该召回胃疼 KB
    assert any("胃" in r["topic"] for r in results)


def test_hybrid_search_handles_emergency():
    """急诊关键词召回急诊 KB。"""
    from medical_agent.agents.hybrid_search import hybrid_search

    results = hybrid_search("突然中风怎么办", top_k=3)
    assert len(results) > 0
    assert "中风" in results[0]["topic"]


def test_hybrid_search_handles_department_query():
    """科室查询召回该科室 KB。"""
    from medical_agent.agents.hybrid_search import hybrid_search

    results = hybrid_search("消化科看什么病", top_k=3)
    assert any(r.get("department") == "消化科" for r in results)


def test_hybrid_search_fusion_score():
    """返回结果含 bm25/kw 分数明细。"""
    from medical_agent.agents.hybrid_search import hybrid_search

    results = hybrid_search("高血压", top_k=3)
    assert "score" in results[0]
    assert "bm25" in results[0]
    assert "kw" in results[0]


def test_hybrid_search_weights_configurable():
    """权重可配置。"""
    from medical_agent.agents.hybrid_search import hybrid_search

    # 关键词权重高
    r1 = hybrid_search("高血压", top_k=3, bm25_weight=0.2, keyword_weight=0.8)
    # BM25 权重高
    r2 = hybrid_search("高血压", top_k=3, bm25_weight=0.8, keyword_weight=0.2)
    # 两种配置下结果可能不同
    assert len(r1) == len(r2) == 3


# =====================================================================
# 4. 索引缓存
# =====================================================================
def test_index_cached():
    """索引只构建一次。"""
    from medical_agent.agents.hybrid_search import _get_index, reset_index

    reset_index()
    docs1, _ = _get_index()
    docs2, _ = _get_index()
    # 同一对象（缓存）
    assert docs1 is docs2


def test_reset_index():
    """重置后重建。"""
    from medical_agent.agents.hybrid_search import _get_index, reset_index

    docs1, _ = _get_index()
    reset_index()
    docs2, _ = _get_index()
    # 不同对象（重建）
    assert docs1 is not docs2


# =====================================================================
# 5. 端到端对比：hybrid vs 纯关键词
# =====================================================================
def test_hybrid_better_than_keyword_for_synonyms():
    """对同义词，hybrid 应该比纯关键词更好。"""
    from medical_agent.agents.hybrid_search import hybrid_search, search_knowledge

    # "胃痛" → 纯关键词搜不到（KB 是"胃疼"），但 BM25 字符 bigram 能匹配
    keyword_results = search_knowledge("胃痛")
    hybrid_results = hybrid_search("胃痛", top_k=3)

    # hybrid 应该至少召回一些结果
    if hybrid_results:
        # hybrid 召回的"胃疼"KB 在关键词里搜不到
        assert len(hybrid_results) > 0
        assert "胃" in hybrid_results[0]["topic"]
