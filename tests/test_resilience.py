"""健壮性测试：熔断 + 超时 + 错误码 + 重试。"""

import time


# =====================================================================
# 1. 错误码
# =====================================================================
def test_error_code_values():
    """错误码枚举值正确。"""
    from medical_agent.resilience import ErrorCode

    assert ErrorCode.APPT_NO_REMAINING.value == "APPT_001"
    assert ErrorCode.LLM_TIMEOUT.value == "LLM_001"
    assert ErrorCode.GUARD_SENSITIVE.value == "GUARD_001"


def test_app_error_to_dict():
    """AppError 转 dict。"""
    from medical_agent.resilience import AppError, ErrorCode

    e = AppError(ErrorCode.APPT_VERSION_CONFLICT, "版本冲突", details={"expected": 1, "actual": 2})
    d = e.to_dict()
    assert d["success"] is False
    assert d["error_code"] == "APPT_003"
    assert d["error_message"] == "版本冲突"
    assert d["details"]["expected"] == 1


# =====================================================================
# 2. 熔断器
# =====================================================================
def test_circuit_breaker_closed_to_open():
    """连续失败触发 OPEN。"""
    from medical_agent.resilience import CircuitBreaker, AppError, ErrorCode

    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10)

    def fail():
        raise ValueError("boom")

    # 失败 3 次
    for _ in range(3):
        try:
            cb.call(fail)
        except ValueError:
            pass

    assert cb.state == CircuitBreaker.OPEN


def test_circuit_breaker_open_rejects_calls():
    """OPEN 状态直接拒绝。"""
    from medical_agent.resilience import CircuitBreaker, AppError, ErrorCode

    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)

    def fail():
        raise ValueError("boom")

    # 失败 1 次
    try:
        cb.call(fail)
    except ValueError:
        pass

    assert cb.state == CircuitBreaker.OPEN

    # 下一次调用直接被拒
    try:
        cb.call(lambda: "ok")
    except AppError as e:
        assert e.code == ErrorCode.CIRCUIT_OPEN


def test_circuit_breaker_half_open_recovery():
    """OPEN → HALF_OPEN → CLOSED 恢复。"""
    from medical_agent.resilience import CircuitBreaker

    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)

    def fail():
        raise ValueError("boom")

    # 失败 2 次触发 OPEN
    for _ in range(2):
        try:
            cb.call(fail)
        except ValueError:
            pass

    assert cb.state == CircuitBreaker.OPEN

    # 等恢复时间
    time.sleep(0.15)

    # 成功 1 次 → CLOSED
    result = cb.call(lambda: "ok")
    assert result == "ok"
    assert cb.state == CircuitBreaker.CLOSED


def test_circuit_breaker_success_resets():
    """成功后重置失败计数。"""
    from medical_agent.resilience import CircuitBreaker

    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=10)

    def fail():
        raise ValueError("boom")

    # 失败 2 次
    for _ in range(2):
        try:
            cb.call(fail)
        except ValueError:
            pass

    # 成功 1 次
    cb.call(lambda: "ok")

    # 再失败 2 次不应该触发 OPEN（计数被 reset 过）
    for _ in range(2):
        try:
            cb.call(fail)
        except ValueError:
            pass

    assert cb.state == CircuitBreaker.CLOSED


def test_circuit_breaker_reset_method():
    """手动 reset。"""
    from medical_agent.resilience import CircuitBreaker

    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=60)

    try:
        cb.call(lambda: (_ for _ in ()).throw(ValueError("boom")))
    except ValueError:
        pass

    assert cb.state == CircuitBreaker.OPEN

    cb.reset()
    assert cb.state == CircuitBreaker.CLOSED


def test_get_llm_circuit_singleton():
    """LLM 熔断器是单例。"""
    from medical_agent.resilience import get_llm_circuit

    a = get_llm_circuit()
    b = get_llm_circuit()
    assert a is b


# =====================================================================
# 3. 超时
# =====================================================================
def test_timeout_raises_app_error():
    """超时抛 AppError。"""
    from medical_agent.resilience import timeout, AppError, ErrorCode

    @timeout(0.1)
    def slow():
        time.sleep(1)
        return "ok"

    try:
        slow()
    except AppError as e:
        assert e.code == ErrorCode.TIMEOUT


def test_timeout_passes_fast_func():
    """快速函数正常返回。"""
    from medical_agent.resilience import timeout

    @timeout(2.0)
    def fast():
        return "ok"

    assert fast() == "ok"


# =====================================================================
# 4. 重试
# =====================================================================
def test_retry_eventually_succeeds():
    """重试后成功。"""
    from medical_agent.resilience import retry_with_backoff

    call_count = {"n": 0}

    @retry_with_backoff(max_retries=3, base_delay=0.01)
    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise ValueError("transient")
        return "ok"

    result = flaky()
    assert result == "ok"
    assert call_count["n"] == 3


def test_retry_gives_up_after_max():
    """达到最大重试次数后放弃。"""
    from medical_agent.resilience import retry_with_backoff

    call_count = {"n": 0}

    @retry_with_backoff(max_retries=2, base_delay=0.01)
    def always_fail():
        call_count["n"] += 1
        raise ValueError("always")

    try:
        always_fail()
    except ValueError:
        pass

    assert call_count["n"] == 3  # 1 + 2 retries


# =====================================================================
# 5. LLM 集成：invoke_with_protection
# =====================================================================
def test_invoke_with_protection_circuit_open():
    """熔断器 OPEN 时 invoke_with_protection 抛错。"""
    from medical_agent.resilience import get_llm_circuit, AppError, ErrorCode, CircuitBreaker

    cb = get_llm_circuit()
    cb.reset()
    # 强制 OPEN
    def fail():
        raise ValueError("boom")
    for _ in range(10):
        try:
            cb.call(fail)
        except (ValueError, AppError):
            pass

    from unittest.mock import MagicMock
    from medical_agent.llm import invoke_with_protection

    mock_llm = MagicMock()
    try:
        invoke_with_protection(mock_llm, ["test"], timeout_seconds=1.0)
    except AppError as e:
        assert e.code == ErrorCode.CIRCUIT_OPEN
    finally:
        cb.reset()


def test_invoke_with_protection_success():
    """正常调用通过保护。"""
    from medical_agent.resilience import get_llm_circuit

    cb = get_llm_circuit()
    cb.reset()

    from unittest.mock import MagicMock
    from medical_agent.llm import invoke_with_protection

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = "result"

    result = invoke_with_protection(mock_llm, ["test"], timeout_seconds=2.0)
    assert result == "result"
