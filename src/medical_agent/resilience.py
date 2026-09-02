"""健壮性基础设施（v3）。

包含：
1. 统一错误码 ErrorCode
2. 熔断器 CircuitBreaker（CLOSED / OPEN / HALF_OPEN）
3. 超时装饰器 timeout
4. 重试装饰器 retry_with_backoff（指数退避）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import random
import threading
import time
from enum import Enum
from typing import Any, Callable, TypeVar


T = TypeVar("T")


# =====================================================================
# 1. 统一错误码
# =====================================================================
class ErrorCode(str, Enum):
    """统一错误码体系。"""

    # 业务错误（APPT_*）
    APPT_NO_REMAINING = "APPT_001"           # 库存不足
    APPT_SCHEDULE_DISABLED = "APPT_002"      # 排班已停用
    APPT_VERSION_CONFLICT = "APPT_003"       # 版本冲突
    APPT_NOT_FOUND = "APPT_004"              # 找不到预约/排班
    APPT_INVALID_STATUS = "APPT_005"         # 状态机非法转换
    APPT_IDEMPOTENCY_CONFLICT = "APPT_006"   # 幂等键冲突
    APPT_UPSTREAM_CHANGED = "APPT_007"       # 上游有未应用变更

    # 护栏（GUARD_*）
    GUARD_SENSITIVE = "GUARD_001"            # 敏感词
    GUARD_INJECTION = "GUARD_002"            # Prompt Injection
    GUARD_TOO_LONG = "GUARD_003"             # 输入过长
    GUARD_TOO_SHORT = "GUARD_004"            # 输入过短
    GUARD_SPAM = "GUARD_005"                 # 重复字符

    # LLM（LLM_*）
    LLM_TIMEOUT = "LLM_001"                  # 模型超时
    LLM_RATE_LIMIT = "LLM_002"               # 模型限流
    LLM_API_ERROR = "LLM_003"                # 模型 API 错误
    LLM_CIRCUIT_OPEN = "LLM_004"             # 熔断器打开
    LLM_INVALID_RESPONSE = "LLM_005"         # 模型返回无法解析

    # 数据库（DB_*）
    DB_ERROR = "DB_001"                      # 数据库通用错误
    DB_LOCK_TIMEOUT = "DB_002"               # 数据库锁超时

    # 系统（SYS_*）
    INTERNAL = "SYS_001"                     # 内部错误
    TIMEOUT = "SYS_002"                      # 通用超时
    CIRCUIT_OPEN = "SYS_003"                 # 熔断器打开


class AppError(Exception):
    """项目统一异常。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code.value}] {message}")

    def to_dict(self) -> dict:
        return {
            "success": False,
            "error_code": self.code.value,
            "error_message": self.message,
            "details": self.details,
        }


# =====================================================================
# 2. 熔断器
# =====================================================================
class CircuitBreaker:
    """熔断器（CLOSED / OPEN / HALF_OPEN）。

    用法：
        cb = CircuitBreaker("deepseek", failure_threshold=5, recovery_timeout=60)
        try:
            result = cb.call(llm.invoke, prompt)
        except CircuitOpenError:
            return fallback_response
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = self.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_open_time: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == self.OPEN:
                # 检查是否过了恢复期
                if (
                    self._last_open_time is not None
                    and time.time() - self._last_open_time > self.recovery_timeout
                ):
                    self._state = self.HALF_OPEN
                    self._success_count = 0
            return self._state

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """同步执行 + 熔断保护。"""
        # 检查状态
        current_state = self.state
        if current_state == self.OPEN:
            raise AppError(
                ErrorCode.CIRCUIT_OPEN,
                f"熔断器 {self.name} 处于 OPEN 状态，跳过调用",
                details={"recovery_in": self._time_to_recovery()},
            )

        try:
            result = func(*args, **kwargs)
        except Exception as e:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    async def acall(self, func: Callable[..., T], *args, **kwargs) -> T:
        """异步执行 + 熔断保护。"""
        current_state = self.state
        if current_state == self.OPEN:
            raise AppError(
                ErrorCode.CIRCUIT_OPEN,
                f"熔断器 {self.name} 处于 OPEN 状态，跳过调用",
            )

        try:
            result = await func(*args, **kwargs)
        except Exception as e:
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    def _on_success(self) -> None:
        with self._lock:
            if self._state == self.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._state = self.CLOSED
                    self._failure_count = 0
                    self._last_open_time = None
            else:
                self._failure_count = 0

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = self.OPEN
                self._last_open_time = time.time()

    def _time_to_recovery(self) -> float:
        if self._last_open_time is None:
            return 0.0
        return max(0.0, self.recovery_timeout - (time.time() - self._last_open_time))

    def reset(self) -> None:
        """手动重置（运维/测试用）。"""
        with self._lock:
            self._state = self.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_open_time = None


# 全局熔断器（LLM）
_llm_circuit: CircuitBreaker | None = None


def get_llm_circuit() -> CircuitBreaker:
    """获取 LLM 熔断器（单例）。"""
    global _llm_circuit
    if _llm_circuit is None:
        _llm_circuit = CircuitBreaker(
            name="llm",
            failure_threshold=5,
            recovery_timeout=60.0,
        )
    return _llm_circuit


# =====================================================================
# 3. 超时装饰器
# =====================================================================
def timeout(seconds: float):
    """同步函数超时装饰器（用线程池）。"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(func, *args, **kwargs)
                try:
                    return future.result(timeout=seconds)
                except concurrent.futures.TimeoutError:
                    raise AppError(
                        ErrorCode.TIMEOUT,
                        f"{func.__name__} 超时（>{seconds}s）",
                        details={"timeout": seconds},
                    )

        return wrapper

    return decorator


def atimeout(seconds: float):
    """异步函数超时装饰器。"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=seconds)
            except asyncio.TimeoutError:
                raise AppError(
                    ErrorCode.TIMEOUT,
                    f"{func.__name__} 超时（>{seconds}s）",
                )

        return wrapper

    return decorator


# =====================================================================
# 4. 重试装饰器（指数退避）
# =====================================================================
def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exceptions: tuple = (Exception,),
):
    """指数退避重试。"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt == max_retries:
                        break
                    # 指数退避 + 抖动
                    delay = min(max_delay, base_delay * (2 ** attempt))
                    delay = delay * (0.5 + random.random())  # 0.5x-1.5x 抖动
                    time.sleep(delay)
            raise last_exc  # type: ignore

        return wrapper

    return decorator


# =====================================================================
# 5. 综合：with_protection 上下文管理器
# =====================================================================
class ProtectedCall:
    """综合保护：超时 + 熔断 + 重试。"""

    def __init__(
        self,
        *,
        circuit: CircuitBreaker | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 0,
    ):
        self.circuit = circuit
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def __call__(self, func: Callable[..., T], *args, **kwargs) -> T:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if self.timeout_seconds:
                    return timeout(self.timeout_seconds)(self._invoke)(func, *args, **kwargs)
                else:
                    return self._invoke(func, *args, **kwargs)
            except AppError as e:
                if e.code in (ErrorCode.CIRCUIT_OPEN, ErrorCode.TIMEOUT):
                    raise  # 不重试
                last_exc = e
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** attempt))
                else:
                    raise
        raise last_exc  # type: ignore

    def _invoke(self, func, *args, **kwargs):
        if self.circuit:
            return self.circuit.call(func, *args, **kwargs)
        return func(*args, **kwargs)
