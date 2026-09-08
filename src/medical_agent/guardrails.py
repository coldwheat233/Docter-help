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
    # v2 补充：越狱 / 角色扮演 / 编码绕过
    r"无视.{0,8}(规则|限制|指令|约束)",
    r"越狱|jailbreak|\bDAN\b",
    r"(开发者|调试|管理员|维护|无限制|上帝)模式",
    r"假装你(是|没有|可以)",
    r"assume\s+the\s+role",
    r"base64|rot13|十六进制.{0,4}(编码|解码)",
    r"override\s+(safety|rules?|restrictions?)",
]

# 提示词探测模式（v2 新增，独立分类 prompt_probe）
# 场景：患者没有任何正当理由询问系统提示词——宁严勿宽
PROMPT_PROBE_PATTERNS: list[str] = [
    r"提示词",
    r"系统提示",
    r"system\s*(message|instruction|设定)",
    r"你的?(初始|原始|内部|完整)?(指令|规则|设定|人设)",
    r"(告诉|显示|展示|输出|复述|重复|打印|发给我|给我看|念).{0,10}(指令|规则|prompt|设定|上下文)",
    r"你(被|是)(谁|怎么)(设定|编程|训练|指示|要求)",
    r"(逐字|一字不差|原样|完整).{0,6}(输出|复述|重复|打印|背)",
    r"你(收到|得到)的?(指令|消息|邮件)",
    r"(上面|前面|开头)的?(文字|内容|话).{0,4}(是|写)什么",
    r"重复.{0,4}(上面|前面|一切|所有)",
    r"repeat\s+(everything|all|the\s+above)",
    r"print\s+(your|the)\s+(prompt|instructions?|rules?)",
    r"what\s+(are|were)\s+your\s+(instructions?|rules?|prompts?)",
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
_PROBE_REGEX = [re.compile(p, re.IGNORECASE) for p in PROMPT_PROBE_PATTERNS]


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

    # 提示词探测（v2：患者无权了解系统 prompt）
    for pattern in _PROBE_REGEX:
        if pattern.search(text):
            return GuardrailResult(
                False,
                "检测到提示词探测行为",
                "prompt_probe",
                "试图获取系统提示词/内部指令，已拦截",
            )

    return GuardrailResult(True)


def check_output(text: str, *, max_length: int = 4000) -> GuardrailResult:
    """输出侧护栏检查。

    v2 新增泄露检测：回复中若包含任一 Agent 系统提示词的标志性原句
    （签名动态提取自各 prompt，改 prompt 无需同步维护），判定为泄露。
    """
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

    # v2：系统提示词泄露检测
    for sig in _get_leak_signatures():
        if sig in text:
            return GuardrailResult(
                False,
                "输出疑似包含系统提示词内容",
                "leak",
                f"命中泄露签名：{sig[:20]}...",
            )

    return GuardrailResult(True)


# =====================================================================
# 泄露签名（动态提取各 Agent prompt 的标志性行）
# =====================================================================
_LEAK_SIGNATURES_CACHE: list[str] | None = None

# 静态补充：内部标识符/协议串，任何情况下不该出现在给用户的回复里
_STATIC_LEAK_SIGNATURES: list[str] = [
    "transfer_to_",
    "<|im_start|>",
    "<|im_end|>",
    "schedule_id",
    "schedule_version",
    "idempotency_key",
    "remaining_steps",
]


def _get_leak_signatures() -> list[str]:
    """收集泄露签名：各 prompt 的首行/特征行（≥8 字）+ 静态内部标识符。"""
    global _LEAK_SIGNATURES_CACHE
    if _LEAK_SIGNATURES_CACHE is not None:
        return _LEAK_SIGNATURES_CACHE

    sigs: list[str] = list(_STATIC_LEAK_SIGNATURES)
    prompts: list[str] = []
    try:
        from medical_agent.agents.confirmer import CONFIRMER_PROMPT
        from medical_agent.agents.intake import INTAKE_PROMPT
        from medical_agent.agents.knowledge import KNOWLEDGE_PROMPT
        from medical_agent.agents.router import ROUTER_PROMPT
        from medical_agent.agents.scheduler import SCHEDULER_PROMPT
        from medical_agent.graphs.supervisor import SUPERVISOR_PROMPT

        prompts = [
            SUPERVISOR_PROMPT,
            ROUTER_PROMPT,
            INTAKE_PROMPT,
            SCHEDULER_PROMPT,
            CONFIRMER_PROMPT,
            KNOWLEDGE_PROMPT,
        ]
    except Exception:
        pass

    for p in prompts:
        for line in p.splitlines():
            line = line.strip().strip("*#- ")
            # 取足够长、足够特征的行（角色定义句、红线句）
            if len(line) >= 10 and ("你是" in line or "禁止" in line or "必须" in line):
                sigs.append(line)

    _LEAK_SIGNATURES_CACHE = sigs
    return sigs


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
