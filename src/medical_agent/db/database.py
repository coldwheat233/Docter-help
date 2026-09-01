"""数据库连接管理：单例 SQLite 连接，支持 CLI 初始化。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from medical_agent.config import get_settings


# 单例连接
_connection: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    """获取 SQLite 连接（单例）。"""
    global _connection
    if _connection is None:
        settings = get_settings()
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(
            str(db_path),
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,  # LangGraph 多线程调用
        )
        _connection.row_factory = sqlite3.Row
        # 外键约束
        _connection.execute("PRAGMA foreign_keys = ON")
        # WAL 模式提升并发
        _connection.execute("PRAGMA journal_mode = WAL")
    return _connection


def close_db() -> None:
    """关闭连接（测试时用）。"""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def init_db(schema_file: Path | None = None) -> None:
    """根据 schema.sql 初始化表结构（幂等）。"""
    if schema_file is None:
        # src/medical_agent/db/schema.sql
        schema_file = Path(__file__).parent / "schema.sql"

    with open(schema_file, encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_db()
    conn.executescript(schema_sql)
    conn.commit()
    print(f"[OK] database initialized: {get_settings().db_path}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--init":
        init_db()
    else:
        print("用法：python -m medical_agent.db.database --init")
        sys.exit(1)
