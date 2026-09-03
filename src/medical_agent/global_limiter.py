"""全局限流（系统级 token bucket）。

用户级限流是 per-user 限速；全局限流是整个系统的并发控制。
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Optional


class TokenBucket:
    """令牌桶限流器。

    经典算法：
    - 桶容量 = max_tokens
    - 每秒补充 rate tokens
    - 每次请求消耗 1 token
    - 桶空则拒绝

    平滑突发：允许短时 burst 到 max_tokens。
    """

    def __init__(self, max_tokens: int = 100, refill_rate: float = 100.0):
        """
        Args:
            max_tokens: 桶容量（最大突发）
            refill_rate: 每秒补充 tokens
        """
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self._tokens = float(max_tokens)
        self._last_refill = time.time()
        self._lock = Lock()
        # 统计
        self.allowed_count = 0
        self.rejected_count = 0

    def try_acquire(self, tokens: int = 1) -> bool:
        """尝试获取 N 个 token。"""
        with self._lock:
            now = time.time()
            # 补充
            elapsed = now - self._last_refill
            if elapsed > 0:
                self._tokens = min(
                    self.max_tokens,
                    self._tokens + elapsed * self.refill_rate,
                )
                self._last_refill = now

            if self._tokens >= tokens:
                self._tokens -= tokens
                self.allowed_count += 1
                return True
            self.rejected_count += 1
            return False

    def stats(self) -> dict:
        """统计。"""
        with self._lock:
            return {
                "max_tokens": self.max_tokens,
                "refill_rate": self.refill_rate,
                "current_tokens": self._tokens,
                "allowed": self.allowed_count,
                "rejected": self.rejected_count,
            }


# =====================================================================
# 组合：用户级 + 全局
# =====================================================================
class CombinedLimiter:
    """用户级 + 全局组合限流。"""

    def __init__(
        self,
        per_user_max: int = 10,
        per_user_window: int = 60,
        global_max_tokens: int = 100,
        global_refill_rate: float = 50.0,
    ):
        from medical_agent.rate_limit import RateLimiter

        self.user_limiter = RateLimiter(
            max_requests=per_user_max, window_seconds=per_user_window
        )
        self.global_limiter = TokenBucket(
            max_tokens=global_max_tokens, refill_rate=global_refill_rate
        )

    def is_allowed(self, user_id: str) -> tuple[bool, str]:
        """检查限流。

        Returns:
            (allowed, reason)
        """
        # 1. 全局先（便宜）
        if not self.global_limiter.try_acquire():
            return False, "global"

        # 2. 用户级
        allowed, _ = self.user_limiter.is_allowed(user_id)
        if not allowed:
            return False, "user"

        return True, "ok"

    def stats(self) -> dict:
        return {
            "global": self.global_limiter.stats(),
            "users_tracked": self.user_limiter.stats()["tracked_users"],
        }


# 全局单例
_GLOBAL_COMBINED: CombinedLimiter | None = None


def get_combined_limiter() -> CombinedLimiter:
    """获取全局 + 用户级组合限流器。"""
    global _GLOBAL_COMBINED
    if _GLOBAL_COMBINED is None:
        _GLOBAL_COMBINED = CombinedLimiter(
            per_user_max=10,
            per_user_window=60,
            global_max_tokens=200,  # 系统总容量（突发）
            global_refill_rate=50.0,  # 50 RPS
        )
    return _GLOBAL_COMBINED
