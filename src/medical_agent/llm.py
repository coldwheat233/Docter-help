"""LLM 工厂：统一返回 ChatDeepSeek + 自动降级到 ChatOpenAI。

v3 增强：
- 主 LLM：ChatDeepSeek（deepseek-chat）
- 备用 LLM：ChatOpenAI（如有 OPENAI_API_KEY）
- 自动 fallback：主 LLM 失败/超时时切备用
- 流式输出支持
"""

from __future__ import annotations

import os
from typing import Iterator

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, HumanMessage

from medical_agent.config import get_settings


def get_llm(
    *,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    model: str | None = None,
    enable_fallback: bool = True,
) -> BaseChatModel:
    """获取 LLM 实例（主 LLM）。

    Args:
        temperature: 0 表示更确定性
        max_tokens: 单次响应上限
        model: 覆盖默认模型
        enable_fallback: 是否启用自动降级（默认 True）

    Returns:
        ChatDeepSeek 或带 fallback 的包装
    """
    settings = get_settings()
    api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "未设置 DEEPSEEK_API_KEY。\n"
            "1) 编辑项目根目录的 .env，填入 DEEPSEEK_API_KEY=sk-...\n"
            "2) 或设系统环境变量 DEEPSEEK_API_KEY"
        )

    # 设置 LangSmith 环境变量（必须在 import langchain 之前）
    _setup_langsmith_env()

    # 主 LLM
    from langchain_deepseek import ChatDeepSeek

    primary = ChatDeepSeek(
        model=model or settings.deepseek_model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=2,
        api_key=api_key,
        streaming=True,  # 默认启用流式
    )

    # 自动降级
    if enable_fallback and settings.openai_api_key:
        try:
            from langchain_openai import ChatOpenAI

            fallback = ChatOpenAI(
                model=settings.openai_fallback_model or "gpt-4o-mini",
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or "https://api.openai.com/v1",
                streaming=True,
            )
            return primary.with_fallbacks([fallback])
        except Exception as e:
            print(f"[llm] fallback 初始化失败，仅用主 LLM：{e}")
            return primary

    return primary


def _setup_langsmith_env() -> None:
    """设置 LangSmith 环境变量（如果启用）。"""
    settings = get_settings()
    if settings.langsmith_tracing:
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)


def get_mock_llm() -> BaseChatModel:
    """获取 mock LLM（不调用真实 API）。"""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    return FakeListChatModel(
        responses=[
            "我是 mock LLM。实际场景会调用 DeepSeek。",
            "我可以假装路由到 router_agent。",
        ]
    )


# =====================================================================
# 流式输出辅助
# =====================================================================
def stream_llm_response(llm: BaseChatModel, prompt: str) -> Iterator[str]:
    """流式调用 LLM（逐 token 返回）。

    用法：
        llm = get_llm()
        for chunk in stream_llm_response(llm, "你好"):
            print(chunk, end="", flush=True)
    """
    for chunk in llm.stream([HumanMessage(content=prompt)]):
        if isinstance(chunk, AIMessageChunk):
            content = chunk.content
            if isinstance(content, str):
                yield content
            elif isinstance(content, list):
                # 部分模型返回 list[str]
                for item in content:
                    if isinstance(item, str):
                        yield item
