"""RAG 工具：给 Agent 用的知识库检索。

让 knowledge_agent 主动调用 search_medical_knowledge(query)，
内部走 hybrid_search（BM25 + 关键词 + Dense 向量）。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


@tool
def search_medical_knowledge(query: str, top_k: int = 3) -> str:
    """从医学知识库检索相关内容。

    内部使用 3 路融合检索（BM25 + 关键词 + Dense 向量 BGE）。
    适用于：
    - 用户问症状/护理/用药
    - 用户已有预约问注意事项
    - 用户问"挂不上号怎么办"
    - 急诊识别（胸痛/中风/呼吸困难等）

    Args:
        query: 用户的医学问题（自然语言）
        top_k: 返回 top K 条（默认 3）

    Returns:
        JSON 字符串：[{id, topic, department, content, score}, ...]
    """
    from medical_agent.agents.hybrid_search import hybrid_search

    try:
        results = hybrid_search(query, top_k=top_k)
    except Exception as e:
        return json.dumps(
            {
                "success": False,
                "error": f"知识库检索失败：{e}",
                "results": [],
            },
            ensure_ascii=False,
        )

    return json.dumps(
        {
            "success": True,
            "query": query,
            "count": len(results),
            "results": [
                {
                    "id": r.get("id", ""),
                    "topic": r.get("topic", ""),
                    "department": r.get("department", ""),
                    "content": r.get("content", ""),
                    "score": round(r.get("score", 0), 3),
                }
                for r in results
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def all_rag_tools() -> list:
    """返回所有 RAG 工具。"""
    return [search_medical_knowledge]
