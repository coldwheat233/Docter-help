"""混合检索：BM25（稀疏向量）+ 关键词匹配 → 融合打分。

v1 知识库用纯关键词匹配（过于简单）：
- 同义词/近义词查不到（"胃疼" vs "胃痛"）
- 词频不敏感（"感冒" 出现 1 次 vs 100 次同等权重）
- 拼写/字符差异不友好

v2 升级：
- BM25 算法（Okapi BM25，业界标准）
- 关键词匹配（保留字面命中）
- 加权融合：BM25 * 0.6 + 关键词 * 0.4

参考：
- https://en.wikipedia.org/wiki/Okapi_BM25
- rank_bm25 库（未用，自己实现避免外部依赖）

不依赖：numpy / sklearn / chroma / faiss
只依赖：Python 标准库
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from medical_agent.agents.knowledge import KNOWLEDGE_BASE


# =====================================================================
# 中文分词（极简版：jieba 替代品）
# 实际生产应使用 jieba / pkuseg，但 jieba 需安装
# 这里用字符 bigram 近似（中文友好的折中）
# =====================================================================
def tokenize(text: str) -> list[str]:
    """中文友好的分词。

    策略：
    1. 转小写
    2. 英文/数字按词切分
    3. 中文按字符 bigram 切分（"胃疼" → ["胃", "胃疼", "疼"]）
    4. 保留单字符 + 双字符组合

    简化版本，未用 jieba。如需更精确可换 jieba。
    """
    text = text.lower().strip()
    if not text:
        return []

    tokens: list[str] = []

    # 分离中英文
    # 中文 unicode 范围
    zh_pattern = re.compile(r"[一-鿿]+")
    en_pattern = re.compile(r"[a-z0-9]+")

    # 中文部分：字符 bigram + 单字符
    for match in zh_pattern.finditer(text):
        zh = match.group(0)
        # 单字符
        tokens.extend(list(zh))
        # 双字符组合（bigram）
        if len(zh) >= 2:
            for i in range(len(zh) - 1):
                tokens.append(zh[i : i + 2])

    # 英文/数字部分：按词
    for match in en_pattern.finditer(text):
        tokens.append(match.group(0))

    return tokens


# =====================================================================
# BM25 算法
# =====================================================================
class BM25:
    """Okapi BM25 实现。

    参数：
    - k1: 词频饱和度（默认 1.5，业界标准）
    - b: 文档长度归一化（默认 0.75）

    公式（每文档对每查询的得分）：
    score(D, Q) = Σ IDF(qi) * (f(qi,D) * (k1+1)) / (f(qi,D) + k1 * (1 - b + b * |D|/avgdl))
    """

    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.N = len(corpus)
        self.doc_lens = [len(doc) for doc in corpus]
        self.avgdl = sum(self.doc_lens) / self.N if self.N > 0 else 0

        # 文档频率 df[term] = 含 term 的文档数
        df: dict[str, int] = {}
        for doc in corpus:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        self.df = df

        # 预计算 IDF
        self.idf: dict[str, float] = {}
        for term, freq in df.items():
            # IDF = log((N - df + 0.5) / (df + 0.5) + 1)
            idf = math.log((self.N - freq + 0.5) / (freq + 0.5) + 1)
            self.idf[term] = idf

    def score(self, query: list[str], doc_idx: int) -> float:
        """单文档对查询的 BM25 得分。"""
        doc = self.corpus[doc_idx]
        doc_len = self.doc_lens[doc_idx]
        tf = Counter(doc)

        score = 0.0
        for term in query:
            if term not in tf:
                continue
            f = tf[term]
            idf = self.idf.get(term, 0)
            numerator = f * (self.k1 + 1)
            denominator = f + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            score += idf * (numerator / denominator)
        return score

    def rank(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """返回 top_k 个 (doc_idx, score) 按分数降序。"""
        query_tokens = tokenize(query)
        scores = []
        for idx in range(self.N):
            s = self.score(query_tokens, idx)
            if s > 0:
                scores.append((idx, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# =====================================================================
# 知识库构建（一次性）
# =====================================================================
def _build_documents() -> list[dict]:
    """把 KNOWLEDGE_BASE 转成 BM25 文档。

    文档字段 = topic + keywords + content（拼接成大字符串）
    """
    documents = []
    for kb in KNOWLEDGE_BASE:
        text = (
            f"{kb['topic']} {' '.join(kb['keywords'])} "
            f"{kb.get('department', '')} {kb['content']}"
        )
        documents.append({"text": text, "tokens": tokenize(text), "kb": kb})
    return documents


_DOCUMENTS: list[dict] | None = None
_BM25_INDEX: BM25 | None = None


def _get_index() -> tuple[list[dict], BM25]:
    """懒加载 BM25 索引。"""
    global _DOCUMENTS, _BM25_INDEX
    if _DOCUMENTS is None or _BM25_INDEX is None:
        _DOCUMENTS = _build_documents()
        _BM25_INDEX = BM25([doc["tokens"] for doc in _DOCUMENTS])
    return _DOCUMENTS, _BM25_INDEX


def reset_index() -> None:
    """清空索引缓存（知识库更新时调用）。"""
    global _DOCUMENTS, _BM25_INDEX
    _DOCUMENTS = None
    _BM25_INDEX = None


# =====================================================================
# 融合检索
# =====================================================================
def _keyword_score(query: str, kb: dict) -> float:
    """关键词匹配得分（保持 v1 行为）。"""
    query_lower = query.lower()
    score = 0.0
    for kw in kb.get("keywords", []):
        if kw.lower() in query_lower:
            score += 1.0
    if kb.get("topic", "").lower() in query_lower:
        score += 2.0
    if kb.get("department", "").lower() in query_lower:
        score += 1.0
    return score


def hybrid_search(
    query: str,
    top_k: int = 5,
    bm25_weight: float = 0.3,
    keyword_weight: float = 0.2,
    dense_weight: float = 0.5,
) -> list[dict]:
    """BM25 + 关键词 + Dense 3 路融合检索。

    算法：
    1. BM25 召回 top_k * 2 候选
    2. 关键词匹配召回 top_k * 2 候选
    3. Dense 向量召回 top_k * 2 候选
    4. 融合打分：score = bm25_weight * bm25_norm + keyword_weight * kw_norm + dense_weight * dense_norm
    5. 取 top_k

    归一化：每路分数除以该路最大分数（max-norm），归一到 [0, 1]
    """
    documents, bm25_index = _get_index()
    if not documents:
        return []

    # 1. BM25 候选
    bm25_candidates = bm25_index.rank(query, top_k=top_k * 2)
    max_bm25 = max((s for _, s in bm25_candidates), default=1.0) or 1.0
    bm25_scores: dict[int, float] = {
        idx: s / max_bm25 for idx, s in bm25_candidates
    }

    # 2. 关键词候选
    kw_scores_raw: list[tuple[int, float]] = []
    for i, doc in enumerate(documents):
        s = _keyword_score(query, doc["kb"])
        if s > 0:
            kw_scores_raw.append((i, s))
    kw_scores_raw.sort(key=lambda x: x[1], reverse=True)
    kw_candidates = kw_scores_raw[: top_k * 2]
    max_kw = max((s for _, s in kw_candidates), default=1.0) or 1.0
    kw_scores: dict[int, float] = {
        idx: s / max_kw for idx, s in kw_candidates
    }

    # 3. Dense 候选（懒加载）
    dense_scores: dict[int, float] = {}
    try:
        from medical_agent.agents.dense_search import dense_search

        dense_results = dense_search(query, top_k=top_k * 2)
        # dense_search 返回 [{id, topic, ..., score}, ...]
        # 需要映射回 doc_idx
        for r in dense_results:
            doc_id = r.get("id")
            for i, doc in enumerate(documents):
                if doc["kb"]["id"] == doc_id:
                    dense_scores[i] = float(r["score"])
                    break
    except Exception as e:
        # dense 失败时退化为 2 路
        print(f"[hybrid_search] dense 失败：{e}")
        dense_weight = 0.0

    # 4. 融合
    all_indices = (
        set(bm25_scores.keys()) | set(kw_scores.keys()) | set(dense_scores.keys())
    )
    fused: list[tuple[int, float]] = []
    for idx in all_indices:
        b = bm25_scores.get(idx, 0.0)
        k = kw_scores.get(idx, 0.0)
        d = dense_scores.get(idx, 0.0)
        # 归一化权重（防止 dense 失败时总权重 < 1）
        total_weight = bm25_weight + keyword_weight + dense_weight
        score = (bm25_weight * b + keyword_weight * k + dense_weight * d) / total_weight
        if score > 0:
            fused.append((idx, score))

    # 5. 排序取 top_k
    fused.sort(key=lambda x: x[1], reverse=True)
    return [
        {
            **documents[idx]["kb"],
            "score": score,
            "bm25": bm25_scores.get(idx, 0),
            "kw": kw_scores.get(idx, 0),
            "dense": dense_scores.get(idx, 0),
        }
        for idx, score in fused[:top_k]
    ]


# 向后兼容：v1 search_knowledge 用关键词匹配
def search_knowledge(query: str) -> list[dict]:
    """v1 关键词匹配（保留兼容）。

    推荐用 hybrid_search() 获得更好效果。
    """
    results = []
    query_lower = query.lower()
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
