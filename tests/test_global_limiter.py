"""全局限流测试。"""

import pytest
import time


def test_token_bucket_basic_allow():
    """基本通过。"""
    from medical_agent.global_limiter import TokenBucket

    b = TokenBucket(max_tokens=5, refill_rate=1)
    for _ in range(5):
        assert b.try_acquire() is True
    # 6 次应被拒
    assert b.try_acquire() is False


def test_token_bucket_refill():
    """token 补充。"""
    from medical_agent.global_limiter import TokenBucket

    b = TokenBucket(max_tokens=1, refill_rate=10)  # 10/s
    assert b.try_acquire() is True
    assert b.try_acquire() is False  # 立即再来失败
    time.sleep(0.2)
    # 0.2s 应该补充 2 个
    assert b.try_acquire() is True


def test_token_bucket_burst():
    """允许突发到 max_tokens。"""
    from medical_agent.global_limiter import TokenBucket

    b = TokenBucket(max_tokens=10, refill_rate=1)
    # 一次取 10 个 OK
    for _ in range(10):
        assert b.try_acquire() is True
    # 11 个失败
    assert b.try_acquire() is False


def test_token_bucket_stats():
    """统计。"""
    from medical_agent.global_limiter import TokenBucket

    b = TokenBucket(max_tokens=5, refill_rate=1)
    for _ in range(5):
        b.try_acquire()
    b.try_acquire()  # rejected
    s = b.stats()
    assert s["allowed"] == 5
    assert s["rejected"] == 1


def test_combined_limiter_user_limit():
    """用户级限流生效。"""
    from medical_agent.global_limiter import CombinedLimiter

    c = CombinedLimiter(per_user_max=2, per_user_window=60, global_max_tokens=100, global_refill_rate=10)
    # user1 用完
    assert c.is_allowed("user1")[0] is True
    assert c.is_allowed("user1")[0] is True
    # 第三次被用户级限流
    allowed, reason = c.is_allowed("user1")
    assert allowed is False
    assert reason == "user"


def test_combined_limiter_global_limit():
    """全局限流生效。"""
    from medical_agent.global_limiter import CombinedLimiter

    c = CombinedLimiter(per_user_max=100, per_user_window=60, global_max_tokens=2, global_refill_rate=0.1)
    # 2 次后全局用完
    assert c.is_allowed("u1")[0] is True
    assert c.is_allowed("u2")[0] is True
    # 第三次全局拒绝
    allowed, reason = c.is_allowed("u3")
    assert allowed is False
    assert reason == "global"


def test_combined_limiter_check_order():
    """全局先检查（不消耗用户配额）。"""
    from medical_agent.global_limiter import CombinedLimiter

    c = CombinedLimiter(per_user_max=2, per_user_window=60, global_max_tokens=2, global_refill_rate=0.1)
    c.is_allowed("u1")  # 1
    c.is_allowed("u2")  # 2
    # 全局满
    allowed, reason = c.is_allowed("u1")
    assert allowed is False
    assert reason == "global"
    # 用户的限流配额应仍是 2（没消耗）
    # 这点重要：全局拒绝时不应消耗用户配额


def test_get_combined_limiter_singleton():
    """全局单例。"""
    from medical_agent.global_limiter import get_combined_limiter

    a = get_combined_limiter()
    b = get_combined_limiter()
    assert a is b
