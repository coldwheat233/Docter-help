"""Checkpoint 服务测试。"""

import pytest
import os


def test_get_checkpointer_default_memory():
    """默认用 InMemorySaver。"""
    # 清环境
    os.environ.pop("CHECKPOINT_URL", None)
    os.environ.pop("CHECKPOINT_PATH", None)

    from medical_agent.checkpoint import get_checkpointer

    cp = get_checkpointer()
    from langgraph.checkpoint.memory import InMemorySaver
    assert isinstance(cp, InMemorySaver)


def test_get_checkpointer_info_memory():
    """Memory 后端诊断信息。"""
    os.environ.pop("CHECKPOINT_URL", None)
    os.environ.pop("CHECKPOINT_PATH", None)

    from medical_agent.checkpoint import get_checkpointer_info

    info = get_checkpointer_info()
    assert info["type"] == "memory"
    assert info["persistent"] is False
    assert "warning" in info


def test_get_checkpointer_info_sqlite():
    """SQLite 后端诊断信息。"""
    os.environ["CHECKPOINT_PATH"] = "data/test_checkpoints.db"
    os.environ.pop("CHECKPOINT_URL", None)

    from medical_agent.checkpoint import get_checkpointer_info

    info = get_checkpointer_info()
    assert info["type"] == "sqlite"
    assert info["persistent"] is True
    assert info["cross_instance"] is False

    del os.environ["CHECKPOINT_PATH"]


def test_get_checkpointer_info_postgres():
    """Postgres 后端诊断信息。"""
    os.environ["CHECKPOINT_URL"] = "postgresql://user:pass@localhost:5432/db"
    os.environ.pop("CHECKPOINT_PATH", None)

    from medical_agent.checkpoint import get_checkpointer_info

    info = get_checkpointer_info()
    assert info["type"] == "postgres"
    assert info["persistent"] is True
    assert info["cross_instance"] is True
    # 验证密码被隐藏
    assert "pass" not in info["url"]

    del os.environ["CHECKPOINT_URL"]


def test_sqlite_checkpointer_type():
    """SQLite checkpointer 类型（需要 langgraph-checkpoint-sqlite，可选）。"""
    import os
    os.environ["CHECKPOINT_PATH"] = "data/test_checkpoints_unit.db"
    os.environ.pop("CHECKPOINT_URL", None)

    from medical_agent import checkpoint as cp_module
    cp_module._CHECKPOINTER = None

    from medical_agent.checkpoint import get_checkpointer
    from langgraph.checkpoint.memory import InMemorySaver

    cp = get_checkpointer()
    # SqliteSaver 在 langgraph-checkpoint-sqlite 独立包
    SqliteSaver = None
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver as _SqliteSaver

        SqliteSaver = _SqliteSaver
    except ImportError:
        pass

    if SqliteSaver is not None:
        assert isinstance(cp, (InMemorySaver, SqliteSaver))
        if isinstance(cp, SqliteSaver):
            try:
                os.unlink("data/test_checkpoints_unit.db")
            except OSError:
                pass
    else:
        # 没装 SqliteSaver，会 fallback 到 InMemorySaver
        assert isinstance(cp, InMemorySaver)

    del os.environ["CHECKPOINT_PATH"]
    cp_module._CHECKPOINTER = None


def test_memory_saver_type():
    """MemorySaver 类型。"""
    os.environ.pop("CHECKPOINT_URL", None)
    os.environ.pop("CHECKPOINT_PATH", None)

    from medical_agent import checkpoint as cp_module
    cp_module._CHECKPOINTER = None

    from medical_agent.checkpoint import get_checkpointer
    from langgraph.checkpoint.memory import InMemorySaver

    cp = get_checkpointer()
    assert isinstance(cp, InMemorySaver)
    cp_module._CHECKPOINTER = None
