"""Prompt 版本管理：加载 YAML 格式的 prompt 文件。

第 3 周：灰度发布 + 回滚 + A/B 测试。

用法：
    from medical_agent.prompts import load_prompt

    prompt = load_prompt("router")
    # 或指定版本
    prompt = load_prompt("router", version="1.0.0")
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# prompts 目录
PROMPTS_DIR = Path(__file__).parent


@dataclass
class Prompt:
    """加载后的 prompt。"""

    name: str
    version: str
    last_updated: str
    author: str
    changelog: str
    system_prompt: str
    description: str
    tags: list[str]
    raw: dict[str, Any]

    def __repr__(self) -> str:
        return f"<Prompt {self.name}@{self.version} by {self.author}>"


_cache: dict[str, "Prompt"] = {}


def load_prompt(name: str, version: str | None = None) -> Prompt:
    """加载 prompt 文件。

    Args:
        name: prompt 名（如 'router' / 'intake' / 'supervisor'）
        version: 版本号（None = 最新）

    Returns:
        Prompt 对象

    Raises:
        FileNotFoundError: prompt 不存在
        ValueError: 指定版本不存在
    """
    cache_key = f"{name}@{version or 'latest'}"
    if cache_key in _cache:
        return _cache[cache_key]

    yaml_path = PROMPTS_DIR / f"{name}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"Prompt '{name}' 不存在：{yaml_path}")

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if version is not None and data.get("version") != version:
        raise ValueError(
            f"Prompt '{name}' 版本 {version} 不存在（当前 {data.get('version')}）"
        )

    prompt = Prompt(
        name=name,
        version=data.get("version", "0.0.0"),
        last_updated=data.get("last_updated", ""),
        author=data.get("author", ""),
        changelog=data.get("changelog", ""),
        system_prompt=data.get("system_prompt", "").strip(),
        description=data.get("description", ""),
        tags=data.get("tags", []),
        raw=data,
    )

    _cache[cache_key] = prompt
    return prompt


def list_prompts() -> list[dict]:
    """列出所有 prompt 文件。"""
    results = []
    for yaml_path in sorted(PROMPTS_DIR.glob("*.yaml")):
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        results.append(
            {
                "name": yaml_path.stem,
                "version": data.get("version", "0.0.0"),
                "description": data.get("description", ""),
                "last_updated": data.get("last_updated", ""),
                "tags": data.get("tags", []),
            }
        )
    return results


def clear_cache() -> None:
    """清空缓存（测试用）。"""
    _cache.clear()
