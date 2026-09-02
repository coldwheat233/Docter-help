"""DENSE 向量检索：基于 embedding 的语义相似度。

第 1 步：sentence-transformers + bge-small-zh（本地模型，下载一次）
备选：OpenAI text-embedding-3-small（API，需 key）
fallback：伪 embedding（hash-based，最后备选）

存储：
- data/embeddings.npy - 35 KB 的 dense vectors
- data/embeddings_meta.json - 文档元数据

检索：
- query → embed → cosine similarity top-k
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from medical_agent.agents.knowledge import KNOWLEDGE_BASE


# 配置
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EMBEDDINGS_PATH = PROJECT_ROOT / "data" / "embeddings.npy"
EMBEDDINGS_META_PATH = PROJECT_ROOT / "data" / "embeddings_meta.json"


# =====================================================================
# Embedder 抽象
# =====================================================================
class Embedder:
    """Embedding 模型抽象。

    子类：LocalEmbedder（sentence-transformers）/ OpenAIEmbedder / HashEmbedder
    """

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """批量 embedding。返回 shape=(N, dim) 的 numpy array。"""
        raise NotImplementedError

    def embed_query(self, text: str) -> np.ndarray:
        """单 query embedding。返回 shape=(dim,) 的 numpy array。"""
        raise NotImplementedError

    @property
    def dim(self) -> int:
        raise NotImplementedError


class HashEmbedder(Embedder):
    """Fallback embedding（hash-based，无外部依赖）。

    用词袋 + hashing 模拟 embedding。效果差但保证可用。
    主要用于：sentence-transformers 装不上时 fallback。
    """

    def __init__(self, dim: int = 256):
        self._dim = dim
        import hashlib
        self._hashlib = hashlib

    def _hash_token(self, token: str) -> int:
        h = self._hashlib.md5(token.encode("utf-8")).hexdigest()
        return int(h, 16) % self._dim

    def _text_to_vector(self, text: str) -> np.ndarray:
        from medical_agent.agents.hybrid_search import tokenize

        vec = np.zeros(self._dim, dtype=np.float32)
        tokens = tokenize(text)
        for tok in tokens:
            idx = self._hash_token(tok)
            vec[idx] += 1.0
        # 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.array([self._text_to_vector(t) for t in texts], dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self._text_to_vector(text)

    @property
    def dim(self) -> int:
        return self._dim


class LocalEmbedder(Embedder):
    """sentence-transformers 本地 embedding。

    模型：BAAI/bge-small-zh-v1.5（中文，~95MB）
    首次运行会下载模型，之后离线用
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5"):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        # 优先从 HuggingFace 镜像下载（国内）
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        self._model = SentenceTransformer(model_name)
        self._dim = self._model.get_sentence_embedding_dimension()

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.array(self._model.encode(texts, normalize_embeddings=True), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return np.array(self._model.encode([text], normalize_embeddings=True)[0], dtype=np.float32)

    @property
    def dim(self) -> int:
        return self._dim


class OpenAIEmbedder(Embedder):
    """OpenAI text-embedding-3-small embedding。

    需要 OPENAI_API_KEY 环境变量。
    """

    def __init__(self, model: str = "text-embedding-3-small"):
        import os
        from openai import OpenAI

        self.model = model
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY 未设置")
        self._client = OpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL"))

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        # 批量调用（OpenAI 限制 2048 inputs/次）
        response = self._client.embeddings.create(model=self.model, input=texts)
        return np.array([d.embedding for d in response.data], dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]

    @property
    def dim(self) -> int:
        return 1536  # text-embedding-3-small


# =====================================================================
# 选默认 embedder
# =====================================================================
def _pick_default_embedder() -> Embedder:
    """按优先级选 embedder。"""
    # 1. 优先 OpenAI（如果有 key）
    if os.environ.get("OPENAI_API_KEY"):
        try:
            return OpenAIEmbedder()
        except Exception as e:
            print(f"[dense_search] OpenAI 不可用：{e}")

    # 2. 本地 sentence-transformers
    try:
        return LocalEmbedder()
    except Exception as e:
        print(f"[dense_search] Local 不可用：{e}")

    # 3. Fallback hash
    print("[dense_search] 用 hash fallback（效果差）")
    return HashEmbedder(dim=384)


# =====================================================================
# 向量库
# =====================================================================
class VectorIndex:
    """Numpy 向量索引（cosine similarity）。

    文档：35 KB
    存储：embeddings.npy + embeddings_meta.json
    """

    def __init__(self, embedder: Embedder | None = None):
        self.embedder = embedder or _pick_default_embedder()
        self._docs: list[dict] = []
        self._vectors: np.ndarray | None = None
        self._loaded = False

    def build(self) -> None:
        """构建/重建索引。"""
        # 准备文档
        self._docs = [
            {
                "id": kb["id"],
                "topic": kb["topic"],
                "keywords": kb["keywords"],
                "department": kb.get("department", ""),
                "content": kb["content"],
                "text": self._make_doc_text(kb),
            }
            for kb in KNOWLEDGE_BASE
        ]
        # Embed
        texts = [d["text"] for d in self._docs]
        self._vectors = self.embedder.embed_documents(texts)
        # 持久化
        self._save()
        self._loaded = True

    def _make_doc_text(self, kb: dict) -> str:
        """构造 embedding 用的文本（拼接 topic + keywords + content）。"""
        parts = [
            kb["topic"],
            " ".join(kb.get("keywords", [])),
            kb.get("department", ""),
            kb["content"],
        ]
        return " | ".join(parts)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """语义检索。"""
        if not self._loaded:
            self._ensure_loaded()

        # Embed query
        query_vec = self.embedder.embed_query(query)

        # Cosine similarity（已 L2 归一化，直接点积）
        scores = self._vectors @ query_vec

        # Top-k
        top_indices = np.argsort(-scores)[:top_k]
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score > 0:
                doc = {**self._docs[idx], "score": score}
                # 去掉内部字段
                doc.pop("text", None)
                results.append(doc)
        return results

    def _ensure_loaded(self) -> None:
        """懒加载：第一次用时 build。"""
        if self._loaded:
            return
        if EMBEDDINGS_PATH.exists() and EMBEDDINGS_META_PATH.exists():
            try:
                self._vectors = np.load(EMBEDDINGS_PATH)
                with open(EMBEDDINGS_META_PATH, encoding="utf-8") as f:
                    self._docs = json.load(f)
                self._loaded = True
                return
            except Exception as e:
                print(f"[dense_search] 加载缓存失败：{e}")
        # 否则重建
        self.build()

    def _save(self) -> None:
        """持久化到 data/。"""
        EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        np.save(EMBEDDINGS_PATH, self._vectors)
        with open(EMBEDDINGS_META_PATH, "w", encoding="utf-8") as f:
            json.dump(self._docs, f, ensure_ascii=False, indent=2)

    def rebuild(self) -> None:
        """强制重建（KB 变化时用）。"""
        if EMBEDDINGS_PATH.exists():
            EMBEDDINGS_PATH.unlink()
        if EMBEDDINGS_META_PATH.exists():
            EMBEDDINGS_META_PATH.unlink()
        self._loaded = False
        self._ensure_loaded()


# 单例
_INDEX: VectorIndex | None = None


def get_index() -> VectorIndex:
    """获取全局向量索引。"""
    global _INDEX
    if _INDEX is None:
        _INDEX = VectorIndex()
        _INDEX._ensure_loaded()  # 懒加载
    return _INDEX


def reset_index() -> None:
    """清空索引。"""
    global _INDEX
    _INDEX = None


def dense_search(query: str, top_k: int = 5) -> list[dict]:
    """便捷函数：dense 向量检索。"""
    return get_index().search(query, top_k=top_k)
