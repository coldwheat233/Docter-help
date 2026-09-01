"""pytest 共享 fixture。"""

import os
import sys
from pathlib import Path

import pytest

# 把 src 加到 path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture(scope="session", autouse=True)
def setup_env():
    """在所有测试前设置环境变量。"""
    # 不强制要求真实 API key，测试可走 mock
    os.environ.setdefault("MOCK_LLM", "true")
    os.environ.setdefault("DB_PATH", str(PROJECT_ROOT / "data" / "test_medical.db"))
    os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-for-testing")
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    yield


@pytest.fixture
def temp_db_path(tmp_path):
    """每个测试用独立临时数据库。"""
    db_path = tmp_path / "test_medical.db"
    os.environ["DB_PATH"] = str(db_path)
    # 重置 config 缓存
    from medical_agent.config import reload_settings

    reload_settings()
    # 初始化 schema
    from medical_agent.db.database import init_db

    init_db()
    yield db_path
    # 清理
    from medical_agent.db.database import close_db

    close_db()
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def mock_llm():
    """提供 mock LLM。"""
    from medical_agent.llm import get_mock_llm

    return get_mock_llm()
