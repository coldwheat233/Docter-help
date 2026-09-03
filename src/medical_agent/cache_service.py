"""缓存服务（cache_service）。

支持两种后端：
1. LocalCache（SQLite + 进程内 LRU）—— 默认，无需外部依赖
2. RedisCache —— 生产环境，多实例共享

设计：
- 抽象接口 CacheBackend
- 工厂函数 get_cache() 自动选 backend
- 线程安全 / 跨进程安全
- LRU + TTL
"""

from __future__ import annotations

import json
import sqlite3
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from medical_agent.config import get_settings


# =====================================================================
# 抽象接口
# =====================================================================
class CacheBackend(ABC):
    """缓存后端抽象接口。"""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """读缓存。None = miss。"""

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """写缓存。"""

    @abstractmethod
    def delete(self, key: str) -> None:
        """删缓存。"""

    @abstractmethod
    def clear(self) -> None:
        """清空。"""

    @abstractmethod
    def stats(self) -> dict:
        """统计。"""


# =====================================================================
# 本地实现（SQLite + 进程内 LRU）
# =====================================================================
class LocalCache(CacheBackend):
    """SQLite 持久化 + 进程内 LRU。

    适用：单实例 / 多 worker 用 sticky session。
    优势：无需 Redis，零外部依赖。
    """

    def __init__(self, db_path: str = ":memory:", max_size: int = 1000, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        # 进程内 LRU
        self._lru: OrderedDict[str, Any] = OrderedDict()
        self._lock = Lock()
        # SQLite 持久化（异步）
        self._db_path = db_path
        self._db: sqlite3.Connection | None = None
        self._init_db()
        # 统计
        self.hits = 0
        self.misses = 0

    def _init_db(self) -> None:
        if self._db_path == ":memory:":
            self._db = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT,
                expires_at REAL
            )"""
        )
        self._db.commit()

    def _normalize(self, value: Any) -> str:
        """转 JSON 字符串。"""
        return json.dumps(value, ensure_ascii=False, default=str)

    def _denormalize(self, raw: str) -> Any:
        """JSON → 对象。"""
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def get(self, key: str) -> Optional[Any]:
        # 1. 进程内 LRU
        with self._lock:
            if key in self._lru:
                value, expires_at = self._lru[key]
                if expires_at > time.time():
                    self._lru.move_to_end(key)
                    self.hits += 1
                    return value
                else:
                    del self._lru[key]
            self.misses += 1

        # 2. SQLite（fallback）
        if self._db is None:
            return None
        try:
            cur = self._db.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            value_raw, expires_at = row
            if expires_at < time.time():
                self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
                self._db.commit()
                return None
            value = self._denormalize(value_raw)
            # 回填 LRU
            with self._lock:
                self._lru[key] = (value, expires_at)
                if len(self._lru) > self.max_size:
                    self._lru.popitem(last=False)
            self.hits += 1
            return value
        except Exception:
            return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or self.ttl_seconds
        expires_at = time.time() + ttl

        evicted_keys: list[str] = []
        with self._lock:
            if key in self._lru:
                self._lru.move_to_end(key)  # 移到末尾（最近用）
            self._lru[key] = (value, expires_at)
            # 超过容量：删最旧（不是被覆盖的 key）
            while len(self._lru) > self.max_size:
                # 找第一个不是 key 的
                for k in list(self._lru.keys()):
                    if k != key:
                        del self._lru[k]
                        evicted_keys.append(k)
                        break
                else:
                    del self._lru[key]

        # 同步删 SQLite（避免下次从 SQLite 兜底命中）
        if self._db is not None and evicted_keys:
            try:
                for k in evicted_keys:
                    self._db.execute("DELETE FROM cache WHERE key = ?", (k,))
                self._db.commit()
            except Exception:
                pass

        if self._db is not None:
            try:
                self._db.execute(
                    "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
                    (key, self._normalize(value), expires_at),
                )
                self._db.commit()
            except Exception:
                pass

    def delete(self, key: str) -> None:
        with self._lock:
            self._lru.pop(key, None)
        if self._db is not None:
            try:
                self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
                self._db.commit()
            except Exception:
                pass

    def clear(self) -> None:
        with self._lock:
            self._lru.clear()
        if self._db is not None:
            try:
                self._db.execute("DELETE FROM cache")
                self._db.commit()
            except Exception:
                pass

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "backend": "local",
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hits / total if total else 0,
            "size": len(self._lru),
        }


# =====================================================================
# Redis 实现（生产环境用）
# =====================================================================
class RedisCache(CacheBackend):
    """Redis 后端缓存（多实例共享）。

    需要 `pip install redis`。
    """

    def __init__(self, redis_url: str, ttl_seconds: int = 300, prefix: str = "medical:"):
        try:
            import redis  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "需要 redis 库：pip install redis"
            ) from e
        self._client = redis.from_url(redis_url)
        self.ttl_seconds = ttl_seconds
        self.prefix = prefix
        self.hits = 0
        self.misses = 0

    def _k(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def get(self, key: str) -> Optional[Any]:
        raw = self._client.get(self._k(key))
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw.decode() if isinstance(raw, bytes) else raw

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or self.ttl_seconds
        self._client.setex(self._k(key), ttl, json.dumps(value, ensure_ascii=False, default=str))

    def delete(self, key: str) -> None:
        self._client.delete(self._k(key))

    def clear(self) -> None:
        # 删带 prefix 的所有 key
        cursor = 0
        while True:
            cursor, keys = self._client.scan(cursor=cursor, match=f"{self.prefix}*", count=100)
            if keys:
                self._client.delete(*keys)
            if cursor == 0:
                break

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "backend": "redis",
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hits / total if total else 0,
        }


# =====================================================================
# 工厂
# =====================================================================
_BACKEND: CacheBackend | None = None


def get_cache() -> CacheBackend:
    """获取全局缓存后端。

    优先用 Redis（如果 REDIS_URL 配了），否则用 LocalCache。
    """
    global _BACKEND
    if _BACKEND is None:
        settings = get_settings()
        redis_url = os.environ.get("REDIS_URL", "")

        if redis_url:
            try:
                _BACKEND = RedisCache(redis_url=redis_url)
                return _BACKEND
            except Exception as e:
                print(f"[cache] Redis 初始化失败，fallback 到 LocalCache：{e}")

        # Fallback: LocalCache
        cache_path = settings.db_path.parent / "cache.sqlite"
        _BACKEND = LocalCache(db_path=str(cache_path), max_size=1000, ttl_seconds=300)

    return _BACKEND


def reset_cache() -> None:
    """重置全局缓存（测试用）。"""
    global _BACKEND
    if _BACKEND is not None:
        _BACKEND.clear()
    _BACKEND = None


# 兼容旧接口
import os  # noqa: E402  放在最后因为 get_cache 用到
