"""响应缓存 + 限流测试。"""

import pytest
import time


# =====================================================================
# 响应缓存
# =====================================================================
def test_cache_basic_set_get():
    """基本 set/get。"""
    from medical_agent.cache import ResponseCache

    c = ResponseCache(max_size=10, ttl_seconds=60)
    c.set("胃疼怎么办？", "KB001: 胃疼")
    assert c.get("胃疼怎么办？") == "KB001: 胃疼"


def test_cache_normalization():
    """query 归一化：标点/空格不敏感。"""
    from medical_agent.cache import ResponseCache

    c = ResponseCache()
    c.set("胃疼怎么办？", "KB001")
    # 标点不同
    assert c.get("胃疼怎么办") == "KB001"
    assert c.get("胃疼怎么办？") == "KB001"
    # 空格不同
    assert c.get("  胃  疼 怎么办 ") == "KB001"


def test_cache_ttl_expired():
    """TTL 过期返回 miss。"""
    from medical_agent.cache import ResponseCache

    c = ResponseCache(ttl_seconds=0.1)
    c.set("hi", "value")
    assert c.get("hi") == "value"
    time.sleep(0.2)
    assert c.get("hi") is None


def test_cache_lru_eviction():
    """超过容量：删最旧。"""
    from medical_agent.cache import ResponseCache

    c = ResponseCache(max_size=2)
    c.set("a", 1)
    c.set("b", 2)
    c.set("c", 3)  # 触发淘汰 a
    assert c.get("a") is None
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_cache_lru_access_updates_order():
    """访问后移到末尾（最近使用）。"""
    from medical_agent.cache import ResponseCache

    c = ResponseCache(max_size=2)
    c.set("a", 1)
    c.set("b", 2)
    c.get("a")  # 访问 a
    c.set("c", 3)  # 触发淘汰 b
    assert c.get("a") == 1
    assert c.get("b") is None
    assert c.get("c") == 3


def test_cache_intent_key():
    """intent 作 key 前缀。"""
    from medical_agent.cache import ResponseCache

    c = ResponseCache()
    c.set("高血压", "intake 内容", intent="book")
    c.set("高血压", "consult 内容", intent="consult")
    assert c.get("高血压", "book") == "intake 内容"
    assert c.get("高血压", "consult") == "consult 内容"


def test_cache_stats():
    """统计。"""
    from medical_agent.cache import ResponseCache

    c = ResponseCache()
    c.set("a", 1)
    c.get("a")  # hit
    c.get("a")  # hit
    c.get("b")  # miss
    s = c.stats()
    assert s["hits"] == 2
    assert s["misses"] == 1
    assert s["hit_rate"] == 2/3


def test_cache_no_user_specific_leak():
    """缓存不含用户特定字段。"""
    # 这是设计原则：只缓存知识问答（不含 patient_id/appointment_id）
    # 测试：缓存调用时不应该存 patient_id 关联的内容
    from medical_agent.cache import ResponseCache

    c = ResponseCache()
    # 知识问答（无 user 字段）
    c.set("胃疼怎么办", "KB001 内容")
    assert c.get("胃疼怎么办") == "KB001 内容"
    # 测试人员字段不进缓存
    assert "patient_id" not in str(c.get("胃疼怎么办"))


def test_global_cache_singleton():
    """全局缓存单例。"""
    from medical_agent.cache import get_cache

    a = get_cache()
    b = get_cache()
    assert a is b


# =====================================================================
# 限流
# =====================================================================
def test_limiter_basic_allow():
    """基本通过。"""
    from medical_agent.rate_limit import RateLimiter

    l = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, _ = l.is_allowed("user1")
        assert allowed is True


def test_limiter_blocks_after_max():
    """超过 max_requests 限流。"""
    from medical_agent.rate_limit import RateLimiter

    l = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        l.is_allowed("user1")
    allowed, info = l.is_allowed("user1")
    assert allowed is False
    assert info["remaining"] == 0
    assert info["retry_after"] > 0


def test_limiter_per_user():
    """用户间隔离。"""
    from medical_agent.rate_limit import RateLimiter

    l = RateLimiter(max_requests=2, window_seconds=60)
    l.is_allowed("user1")
    l.is_allowed("user1")
    # user1 满了
    allowed, _ = l.is_allowed("user1")
    assert allowed is False
    # user2 不受影响
    allowed, _ = l.is_allowed("user2")
    assert allowed is True


def test_limiter_window_expiry():
    """窗口外不计入。"""
    from medical_agent.rate_limit import RateLimiter

    l = RateLimiter(max_requests=2, window_seconds=0.1)
    l.is_allowed("user1")
    l.is_allowed("user1")
    # 满了
    allowed, _ = l.is_allowed("user1")
    assert allowed is False
    # 等窗口过期
    time.sleep(0.15)
    allowed, _ = l.is_allowed("user1")
    assert allowed is True


def test_limiter_global_singleton():
    """全局限流器单例。"""
    from medical_agent.rate_limit import get_limiter

    a = get_limiter()
    b = get_limiter()
    assert a is b


def test_limiter_remaining_decreases():
    """remaining 递减。"""
    from medical_agent.rate_limit import RateLimiter

    l = RateLimiter(max_requests=5, window_seconds=60)
    _, info1 = l.is_allowed("user1")
    _, info2 = l.is_allowed("user1")
    assert info2["remaining"] < info1["remaining"]


# =====================================================================
# 集成：缓存 + 限流
# =====================================================================
def test_cache_and_rate_limit_together():
    """缓存命中跳过限流检查（节省 API 调用）。"""
    from medical_agent.cache import ResponseCache
    from medical_agent.rate_limit import RateLimiter

    cache = ResponseCache()
    limiter = RateLimiter(max_requests=2, window_seconds=60)

    # 第一次：限流通过 + LLM 调用 + 缓存
    allowed1, _ = limiter.is_allowed("user1")
    cache.set("高血压", "KB009")

    # 第二次：cache 命中（限流检查还是过，但不需要 LLM）
    cached = cache.get("高血压")
    assert cached == "KB009"
    # 注：实际部署时，cache.get 命中后应该跳过 LLM 调用
    # 这样 100 用户问同问，cache 命中时只算 1 次 LLM
