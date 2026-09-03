"""用户级限流（rate limit）。

每个用户（按 IP / patient_id）每分钟最多 N 次请求。
超限返回"系统繁忙，请稍后再试"（无感保护）。

算法：滑动窗口 + 内存计数（生产可换 Redis）。
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any


class RateLimiter:
    """滑动窗口限流器。"""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        Args:
            max_requests: 窗口期内最大请求数
            window_seconds: 窗口大小（秒）
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # key: user_id → deque[timestamp]
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def is_allowed(self, user_id: str) -> tuple[bool, dict]:
        """检查用户是否被限流。

        Returns:
            (allowed, info)
            info = {remaining, reset_at, ...}
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            requests = self._requests[user_id]
            # 清掉窗口外的
            while requests and requests[0] < cutoff:
                requests.popleft()

            if len(requests) >= self.max_requests:
                # 限流
                reset_at = requests[0] + self.window_seconds
                return False, {
                    "remaining": 0,
                    "reset_at": reset_at,
                    "retry_after": int(reset_at - now) + 1,
                }

            # 通过
            requests.append(now)
            remaining = self.max_requests - len(requests)
            return True, {
                "remaining": remaining,
                "reset_at": now + self.window_seconds,
            }

    def reset_user(self, user_id: str) -> None:
        """重置某用户限流（测试用）。"""
        with self._lock:
            self._requests.pop(user_id, None)

    def stats(self) -> dict:
        """统计。"""
        with self._lock:
            return {
                "tracked_users": len(self._requests),
                "max_requests": self.max_requests,
                "window_seconds": self.window_seconds,
            }


# 全局单例
_GLOBAL_LIMITER: RateLimiter | None = None


def get_limiter() -> RateLimiter:
    """获取全局限流器。"""
    global _GLOBAL_LIMITER
    if _GLOBAL_LIMITER is None:
        # 默认 10 req/min/user（医疗预约对话，10 次足够）
        _GLOBAL_LIMITER = RateLimiter(max_requests=10, window_seconds=60)
    return _GLOBAL_LIMITER


def check_rate_limit(user_id: str) -> tuple[bool, dict]:
    """检查限流便捷函数。"""
    return get_limiter().is_allowed(user_id)
