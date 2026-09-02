"""Demo 08: BM25 vs 关键词检索对比。

跑法：python -m demos.08_hybrid_search_demo

对比：
- v1 关键词匹配（已 deprecated，但保留兼容）
- v2 BM25 字符 bigram
- v2 融合（BM25 + 关键词）

测试查询：覆盖近义词/科室/急诊/慢病等场景
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from medical_agent.agents.knowledge import KNOWLEDGE_BASE  # noqa: E402
from medical_agent.agents.hybrid_search import (  # noqa: E402
    hybrid_search,
    reset_index,
)


# 旧版纯关键词（保留用于对比）
def keyword_search(query: str) -> list[dict]:
    query_lower = query.lower()
    results = []
    for kb in KNOWLEDGE_BASE:
        score = 0
        for kw in kb["keywords"]:
            if kw.lower() in query_lower:
                score += 1
        if kb["topic"].lower() in query_lower:
            score += 2
        if score > 0:
            results.append({**kb, "score": score})
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def compare_query(query: str) -> None:
    """对比关键词 vs BM25 vs 融合。"""
    print(f"\n{'=' * 60}")
    print(f"查询：{query}")
    print("=" * 60)

    # 关键词
    kw_results = keyword_search(query)
    print(f"\n[关键词匹配] 返回 {len(kw_results)} 条：")
    for i, r in enumerate(kw_results[:3], 1):
        print(f"  {i}. [{r['score']}] {r['topic']}")

    # BM25
    print(f"\n[BM25 融合] 返回 {len(hybrid_search(query, top_k=5))} 条：")
    hybrid_results = hybrid_search(query, top_k=5)
    for i, r in enumerate(hybrid_results[:3], 1):
        print(
            f"  {i}. [score={r['score']:.2f}, bm25={r['bm25']:.2f}, kw={r['kw']:.2f}] {r['topic']}"
        )


def main() -> int:
    reset_index()  # 重新构建索引

    print("=" * 60)
    print("Demo 08: 关键词 vs BM25 融合检索对比")
    print("=" * 60)
    print(f"知识库：{len(KNOWLEDGE_BASE)} 条")
    print(f"BM25: k1=1.5, b=0.75（业界标准）")
    print(f"融合权重: BM25=0.6, 关键词=0.4")

    test_queries = [
        # 1. 同义词
        "胃痛怎么办",  # KB001 是"胃疼"
        # 2. 字面匹配
        "高血压平时注意什么",
        # 3. 急诊
        "突然中风怎么办",
        # 4. 科室
        "消化科看什么病",
        # 5. 慢病
        "糖尿病怎么管理",
        # 6. 特殊人群
        "孕妇感冒能吃药吗",
        # 7. 多义词
        "感冒发烧",
    ]

    for q in test_queries:
        compare_query(q)

    print()
    print("=" * 60)
    print("✅ 结论：")
    print("  - 同义词场景（胃痛 vs 胃疼）：BM25 强")
    print("  - 字面匹配场景：关键词 + BM25 融合更强")
    print("  - 急诊识别：BM25 字符 bigram 也能召回（中风 → 中风 FAST）")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
