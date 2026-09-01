"""输入护栏中间件（v1）。

实现：
1. 敏感词过滤（医保诈骗、违规查询、暴力威胁）
2. Prompt Injection 检测（"忽略之前指令"、"假装你是..."）
3. 长度限制
4. 输出侧护栏（v1 简单：长度 + 重复字符）

第 1 周实现：纯规则（正则 + 黑名单）；不调 LLM 做内容审核（避免成本+延迟）
生产化：调内容安全 API（如百度、阿里云内容审核）
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# =====================================================================
# 黑名单
# =====================================================================
# 敏感词（医疗场景）
SENSITIVE_KEYWORDS: list[str] = [
    # 医保诈骗
    "医保套现", "骗保", "伪造病历",
    # 暴力威胁
    "杀医生", "炸医院", "持刀",
    # 违规查询
    "查别人病历", "偷看", "盗用",
    # 黄色/毒品
    "毒品", "摇头丸", "冰毒",
]

# Prompt Injection 模式
INJECTION_PATTERNS: list[str] = [
    r"忽略.{0,10}之前.{0,10}(指令|规则|提示)",
    r"ignore\s+(previous|all|above).{0,10}(instructions?|rules?|prompts?)",
    r"disregard.{0,10}(previous|all|above)",
    r"你现在是",
    r"forget\s+everything",
    r"你扮演",
    r"act\s+as\s+(if|a|an)\s+",
    r"pretend\s+(to\s+be|you\s+are)",
    r"system\s*prompt",
    r"<\|im_start\|>",  # ChatML 注入
    r"<\|im_end\|>",
    r"###\s*instruction",
]


# =====================================================================
# 校验结果
# =====================================================================
@dataclass
class GuardrailResult:
    """护栏检查结果。"""

    is_safe: bool
    reason: str | None = None
    category: str | None = None  # 'sensitive' / 'injection' / 'too_long' / 'too_short'
    details: str | None = None

    def to_dict(self) -> dict:
        return {
            "is_safe": self.is_safe,
            "reason": self.reason,
            "category": self.category,
            "details": self.details,
        }


# =====================================================================
# 校验函数
# =====================================================================
# 编译正则（启动时一次）
_INJECTION_REGEX = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def check_input(
    text: str,
    *,
    max_length: int = 500,
    min_length: int = 1,
) -> GuardrailResult:
    """输入侧护栏检查。

    Args:
        text: 用户输入
        max_length: 最大长度（默认 500 字）
        min_length: 最小长度（默认 1）

    Returns:
        GuardrailResult
    """
    if not text or not text.strip():
        return GuardrailResult(False, "输入为空", "too_short")

    if len(text) > max_length:
        return GuardrailResult(
            False,
            f"输入过长（{len(text)} > {max_length}）",
            "too_long",
        )

    # 敏感词
    for kw in SENSITIVE_KEYWORDS:
        if kw in text:
            return GuardrailResult(
                False,
                f"包含敏感词：{kw}",
                "sensitive",
                f"检测到敏感词 '{kw}'，无法处理",
            )

    # Prompt Injection
    for pattern in _INJECTION_REGEX:
        if pattern.search(text):
            return GuardrailResult(
                False,
                "疑似 Prompt Injection 攻击",
                "injection",
                "检测到试图绕过系统指令的内容",
            )

    return GuardrailResult(True)


def check_output(text: str, *, max_length: int = 4000) -> GuardrailResult:
    """输出侧护栏检查（v1 简单）。"""
    if not text:
        return GuardrailResult(False, "输出为空", "empty")

    if len(text) > max_length:
        return GuardrailResult(
            False,
            f"输出过长（{len(text)} > {max_length}）",
            "too_long",
        )

    # 检测重复字符刷屏（如 "啊啊啊啊啊啊啊啊"）
    if re.search(r"(.)\1{20,}", text):
        return GuardrailResult(
            False,
            "输出包含异常重复字符",
            "spam",
        )

    return GuardrailResult(True)


# =====================================================================
# 装饰器：用于保护工具/Agent
# =====================================================================
def guard_input(func):
    """装饰器：保护 LangChain 工具函数。

    用法：
        @tool
        @guard_input
        def my_tool(x: str) -> str:
            ...
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # 检查所有字符串参数
        for arg in list(args) + list(kwargs.values()):
            if isinstance(arg, str):
                result = check_input(arg)
                if not result.is_safe:
                    return f"[guardrail blocked] {result.reason}"
        return func(*args, **kwargs)

    return wrapper
