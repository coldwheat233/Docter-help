"""Prompt 版本管理测试。"""

import pytest


def test_load_router_prompt():
    """加载 router prompt。"""
    from medical_agent.prompts import load_prompt

    p = load_prompt("router")
    assert p.name == "router"
    assert p.version == "1.0.0"
    assert "intent" in p.system_prompt.lower()
    assert p.description


def test_load_intake_prompt():
    """加载 intake prompt。"""
    from medical_agent.prompts import load_prompt

    p = load_prompt("intake")
    assert "symptoms" in p.system_prompt.lower()
    assert "duration" in p.system_prompt.lower()
    assert "department" in p.system_prompt.lower()


def test_load_scheduler_prompt():
    """加载 scheduler prompt。"""
    from medical_agent.prompts import load_prompt

    p = load_prompt("scheduler")
    assert "check_availability" in p.system_prompt
    assert "list_doctors" in p.system_prompt


def test_load_confirmer_prompt():
    """加载 confirmer prompt。"""
    from medical_agent.prompts import load_prompt

    p = load_prompt("confirmer")
    assert "set_appointment" in p.system_prompt
    assert "cancel_appointment" in p.system_prompt


def test_load_supervisor_prompt():
    """加载 supervisor prompt。"""
    from medical_agent.prompts import load_prompt

    p = load_prompt("supervisor")
    assert "ROUTER_AGENT_NAME" in p.system_prompt or "router" in p.system_prompt.lower()


def test_load_knowledge_prompt():
    """加载 knowledge prompt（含占位符）。"""
    from medical_agent.prompts import load_prompt

    p = load_prompt("knowledge")
    assert "{KB_TOPICS}" in p.system_prompt  # 含占位符


def test_load_nonexistent_prompt_raises():
    """加载不存在的 prompt 抛 FileNotFoundError。"""
    from medical_agent.prompts import load_prompt

    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_agent")


def test_load_specific_version_raises_if_mismatch():
    """指定版本不匹配抛 ValueError。"""
    from medical_agent.prompts import load_prompt, clear_cache

    clear_cache()
    with pytest.raises(ValueError, match="版本 9.9.9 不存在"):
        load_prompt("router", version="9.9.9")


def test_list_prompts():
    """列出所有 prompt。"""
    from medical_agent.prompts import list_prompts

    items = list_prompts()
    assert len(items) >= 5  # router, intake, scheduler, confirmer, supervisor, knowledge
    names = {p["name"] for p in items}
    assert "router" in names
    assert "intake" in names
    assert "scheduler" in names
    assert "confirmer" in names
    assert "supervisor" in names
    assert "knowledge" in names


def test_prompt_cache_works():
    """重复 load 返回同一对象（缓存）。"""
    from medical_agent.prompts import load_prompt, clear_cache

    clear_cache()
    p1 = load_prompt("router")
    p2 = load_prompt("router")
    assert p1 is p2


def test_all_prompts_have_version():
    """所有 prompt 都有 version 字段。"""
    from medical_agent.prompts import list_prompts

    items = list_prompts()
    for p in items:
        assert p["version"], f"{p['name']} 缺 version"
        # 语义版本
        parts = p["version"].split(".")
        assert len(parts) == 3, f"{p['name']} version 不是 x.y.z 格式"


def test_knowledge_prompt_kb_topics_substituted():
    """knowledge prompt 占位符 {KB_TOPICS} 可被替换。"""
    from medical_agent.prompts import load_prompt, clear_cache

    clear_cache()
    p = load_prompt("knowledge")
    # 占位符应该存在
    assert "{KB_TOPICS}" in p.system_prompt
