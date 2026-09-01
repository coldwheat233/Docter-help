"""配置加载：从项目根的 .env 文件读取。

设计原则：
- 路径常量集中在这里，避免散落在各处
- 用 pydantic-settings 做类型校验
- 不在 import 时副作用加载，而是在显式调用 get_settings() 时加载
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录：medical-appointment-agent/
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    """运行时配置。所有字段必填，无 None；用环境变量覆盖。"""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # DeepSeek
    deepseek_api_key: str = Field(default="", description="DeepSeek API Key")
    deepseek_model: str = Field(default="deepseek-chat", description="默认 deepseek-chat")

    # OpenAI 备用（v3 模型降级）
    openai_api_key: str = Field(default="", description="OpenAI 备用 API Key")
    openai_base_url: str = Field(default="https://api.openai.com/v1", description="OpenAI 兼容 base URL")
    openai_fallback_model: str = Field(default="gpt-4o-mini", description="OpenAI 备用模型")

    # LangSmith
    langsmith_tracing: bool = Field(default=False, description="是否启用 LangSmith 追踪")
    langsmith_api_key: str = Field(default="", description="LangSmith API Key")
    langsmith_project: str = Field(default="medical-agent", description="LangSmith 项目名")

    # 数据库
    db_path: Path = Field(default=DATA_DIR / "medical.db", description="SQLite 数据库路径")

    # 运行模式
    mock_llm: bool = Field(default=False, description="用 mock 替代真实 LLM")

    # 业务配置
    schedule_days: int = Field(default=30, ge=1, le=365, description="排班生成天数")
    department_count: int = Field(default=5, ge=1, le=50, description="科室数量")
    doctor_count: int = Field(default=20, ge=1, le=200, description="医生数量")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取单例配置。"""
    return Settings()


def reload_settings() -> Settings:
    """清除缓存重新加载（用于测试或动态切换 .env）。"""
    get_settings.cache_clear()
    return get_settings()
