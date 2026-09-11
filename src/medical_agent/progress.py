"""工具/节点的用户可见进度事件。

LangGraph custom stream：工具内调 emit_progress("正在查询排班…")，
SSE 端点（web/api.py /api/chat/stream）以 stream_mode=["updates","custom"]
捕获并推给前端。

设计约束：
- 只发白名单静态话术，永不透传工具参数（schedule_id/version 等内部字段）
- 非流式上下文（pytest、直接 .func() 调用）下静默 no-op
"""

from __future__ import annotations


def emit_progress(label: str) -> None:
    """发一条用户可见的进度事件。非流式上下文下静默忽略。"""
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        writer({"type": "progress", "label": label})
    except Exception:
        pass
