"""缓存服务测试。"""

import pytest


# =====================================================================
# LocalCache
# =====================================================================
def test_local_cache_basic():
    """基本 set/get。"""
    from medical_agent.cache_service import LocalCache

    c = LocalCache(db_path=":memory:")
    c.set("k1", "v1")
    assert c.get("k1") == "v1"


def test_local_cache_complex_value():
    """复杂值（dict/list）。"""
    from medical_agent.cache_service import LocalCache

    c = LocalCache(db_path=":memory:")
    c.set("k1", {"a": 1, "b": [1, 2, 3]})
    assert c.get("k1") == {"a": 1, "b": [1, 2, 3]}


def test_local_cache_ttl():
    """TTL 过期。"""
    from medical_agent.cache_service import LocalCache

    c = LocalCache(db_path=":memory:", ttl_seconds=0.1)
    c.set("k1", "v1")
    assert c.get("k1") == "v1"
    import time
    time.sleep(0.15)
    assert c.get("k1") is None


def test_local_cache_lru_eviction():
    """LRU 淘汰。"""
    from medical_agent.cache_service import LocalCache

    c = LocalCache(db_path=":memory:", max_size=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # 淘汰 a
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_local_cache_delete():
    """删除。"""
    from medical_agent.cache_service import LocalCache

    c = LocalCache(db_path=":memory:")
    c.set("k1", "v1")
    c.delete("k1")
    assert c.get("k1") is None


def test_local_cache_clear():
    """清空。"""
    from medical_agent.cache_service import LocalCache

    c = LocalCache(db_path=":memory:")
    c.set("a", 1)
    c.set("b", 2)
    c.clear()
    assert c.get("a") is None
    assert c.get("b") is None


def test_local_cache_stats():
    """统计。"""
    from medical_agent.cache_service import LocalCache

    c = LocalCache(db_path=":memory:")
    c.set("a", 1)
    c.get("a")
    c.get("a")
    c.get("b")
    s = c.stats()
    assert s["hits"] == 2
    assert s["misses"] == 1
    assert s["backend"] == "local"


def test_local_cache_persistence():
    """SQLite 持久化。"""
    import tempfile
    import gc
    from medical_agent.cache_service import LocalCache

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name

    try:
        c1 = LocalCache(db_path=path)
        c1.set("k1", "v1")
        c1.set("k2", "v2")
        c1._db.close()
        del c1
        gc.collect()

        c2 = LocalCache(db_path=path)
        assert c2.get("k1") == "v1"
        assert c2.get("k2") == "v2"
        c2._db.close()
    finally:
        import os
        try:
            os.unlink(path)
        except OSError:
            pass


# =====================================================================
# Redis（如果可用）
# =====================================================================
def test_redis_cache_if_available():
    """Redis 后端（如果 REDIS_URL 配了）。"""
    import os
    if not os.environ.get("REDIS_URL"):
        pytest.skip("REDIS_URL 未配")

    from medical_agent.cache_service import RedisCache

    c = RedisCache(redis_url=os.environ["REDIS_URL"], prefix="test:")
    c.clear()
    c.set("k1", "v1")
    assert c.get("k1") == "v1"
    c.delete("k1")
    assert c.get("k1") is None


# =====================================================================
# 工厂
# =====================================================================
def test_get_cache_default_local():
    """默认 local backend。"""
    from medical_agent.cache_service import get_cache, reset_cache

    reset_cache()
    c = get_cache()
    s = c.stats()
    assert s["backend"] in ("local", "redis")


def test_cache_singleton():
    """全局单例。"""
    from medical_agent.cache_service import get_cache

    a = get_cache()
    b = get_cache()
    assert a is b
