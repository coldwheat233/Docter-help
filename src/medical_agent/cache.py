"""响应缓存（response cache）。

同问同答复用：用户/不同用户问同一个问题，第二次直接返回缓存。
LRU + TTL + 关键词归一化。

注意：
- 缓存内容不含系统字段（patient_id、schedule_id、version）
- 缓存 key 基于 (intent + 关键实体)，不含 user-specific 信息
- TTL 默认 5 分钟（医疗知识更新慢，但安全起见）
"""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from threading import Lock
from typing import Any


class ResponseCache:
    """LRU + TTL 响应缓存（线程安全）。"""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = Lock()
        # 命中统计
        self.hits = 0
        self.misses = 0

    def _normalize_query(self, query: str) -> str:
        """归一化 query：去标点/空格/小写。"""
        if not query:
            return ""
        # 去标点 + 空格
        s = re.sub(r"[\s,.!?，。！？、:：;；\"'""'']+", "", query)
        return s.lower().strip()

    def _make_key(self, query: str, intent: str = "") -> str:
        """构造缓存 key。"""
        nq = self._normalize_query(query)
        if intent:
            nq = f"{intent}::{nq}"
        return hashlib.md5(nq.encode("utf-8")).hexdigest()[:16]

    def get(self, query: str, intent: str = "") -> Any | None:
        """获取缓存（None = miss）。"""
        key = self._make_key(query, intent)
        with self._lock:
            if key not in self._cache:
                self.misses += 1
                return None
            ts, value = self._cache[key]
            # TTL 检查
            if time.time() - ts > self.ttl_seconds:
                del self._cache[key]
                self.misses += 1
                return None
            # 移到末尾（LRU）
            self._cache.move_to_end(key)
            self.hits += 1
            return value

    def set(self, query: str, value: Any, intent: str = "") -> None:
        """设置缓存。"""
        key = self._make_key(query, intent)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.time(), value)
            # 超过容量：删最旧
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        """统计信息。"""
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": len(self._cache),
            "hit_rate": self.hits / total if total else 0,
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds,
        }


# 全局单例
_GLOBAL_CACHE: ResponseCache | None = None


def get_cache() -> ResponseCache:
    """获取全局缓存。"""
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        _GLOBAL_CACHE = ResponseCache()
    return _GLOBAL_CACHE


def cached_response(query: str, intent: str = "") -> Any | None:
    """读缓存便捷函数。"""
    return get_cache().get(query, intent)


def cache_response(query: str, value: Any, intent: str = "") -> None:
    """写缓存便捷函数。"""
    get_cache().set(query, value, intent)
