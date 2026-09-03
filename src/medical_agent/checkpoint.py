"""Checkpoint 服务（持久化 Agent State）。

抽象接口 + 多种后端：
1. MemorySaver —— 进程内存（开发/测试）
2. SqliteSaver —— SQLite 文件（轻量持久化，单实例）
3. PostgresSaver —— PostgreSQL（生产，跨实例）

LangGraph 0.3+ 内置：
- langgraph.checkpoint.memory.InMemorySaver
- langgraph.checkpoint.sqlite.SqliteSaver
- langgraph.checkpoint.postgres.PostgresSaver（需 pip install langgraph-checkpoint-postgres）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from medical_agent.config import get_settings


def get_checkpointer():
    """获取当前配置的 checkpointer。

    优先级：
    1. 环境变量 CHECKPOINT_URL=postgres://...  → PostgresSaver
    2. 环境变量 CHECKPOINT_PATH=data/checkpoints.db  → SqliteSaver
    3. 默认  → InMemorySaver（仅开发/测试）

    Returns:
        LangGraph checkpointer 实例
    """
    import os

    # 1. Postgres
    pg_url = os.environ.get("CHECKPOINT_URL", "")
    if pg_url.startswith("postgres://") or pg_url.startswith("postgresql://"):
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            checkpointer = PostgresSaver.from_conn_string(pg_url)
            checkpointer.setup()  # 自动建表
            return checkpointer
        except ImportError:
            print("[checkpoint] langgraph-checkpoint-postgres 未装，回退到 SQLite")
        except Exception as e:
            print(f"[checkpoint] PostgresSaver 失败：{e}，回退到 SQLite")

    # 2. SQLite
    sqlite_path = os.environ.get("CHECKPOINT_PATH", "")
    if sqlite_path:
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver

            Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
            return SqliteSaver.from_conn_string(sqlite_path)
        except ImportError:
            print("[checkpoint] SqliteSaver 不可用，回退到 MemorySaver")
        except Exception as e:
            print(f"[checkpoint] SqliteSaver 失败：{e}，回退到 MemorySaver")

    # 3. Memory（默认）
    from langgraph.checkpoint.memory import InMemorySaver
    return InMemorySaver()


def get_checkpointer_info() -> dict[str, Any]:
    """返回当前 checkpointer 类型（用于诊断）。"""
    import os

    pg_url = os.environ.get("CHECKPOINT_URL", "")
    sqlite_path = os.environ.get("CHECKPOINT_PATH", "")

    if pg_url:
        return {
            "type": "postgres",
            "url": pg_url.split("@")[-1] if "@" in pg_url else pg_url,  # 隐藏密码
            "persistent": True,
            "cross_instance": True,
        }
    if sqlite_path:
        return {
            "type": "sqlite",
            "path": sqlite_path,
            "persistent": True,
            "cross_instance": False,
        }
    return {
        "type": "memory",
        "persistent": False,
        "cross_instance": False,
        "warning": "开发模式。重启会丢失所有用户状态。生产请用 CHECKPOINT_PATH 或 CHECKPOINT_URL",
    }
