"""急诊识别测试。"""

import pytest


def test_detect_emergency_chest_pain():
    """胸痛 = 急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, matched = detect_emergency("突然胸痛，呼吸困难")
    assert is_em is True
    assert "突然胸痛" in matched or "呼吸困难" in matched


def test_detect_emergency_stroke():
    """中风 = 急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, matched = detect_emergency("我爸爸突然口角歪斜，言语不清")
    assert is_em is True
    assert any(k in matched for k in ["口角歪斜", "言语不清"])


def test_detect_emergency_breathing():
    """呼吸困难 = 急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, matched = detect_emergency("孩子喘不上气，嘴唇发紫")
    assert is_em is True
    assert "喘不上气" in matched or "嘴唇发紫" in matched


def test_detect_emergency_bleeding():
    """大出血 = 急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, matched = detect_emergency("手被割伤，血流不止")
    assert is_em is True
    assert "血流不止" in matched


def test_detect_emergency_allergy():
    """过敏性休克 = 急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, matched = detect_emergency("吃虾后全身红疹，呼吸困难")
    assert is_em is True
    assert "呼吸困难" in matched


def test_no_emergency_normal_gastric():
    """普通胃疼不是急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, _ = detect_emergency("我胃疼了一周")
    assert is_em is False


def test_no_emergency_chronic():
    """慢性病不是急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, _ = detect_emergency("高血压平时注意什么")
    assert is_em is False


def test_no_emergency_common_cold():
    """普通感冒不是急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, _ = detect_emergency("感冒发烧怎么办")
    assert is_em is False


def test_emergency_response_contains_120():
    """急诊响应含 120 指引。"""
    from medical_agent.emergency import build_emergency_response, detect_emergency

    is_em, matched = detect_emergency("突然胸痛")
    assert is_em
    response = build_emergency_response(matched)
    assert "120" in response
    assert "急诊" in response
    assert "立即" in response


def test_emergency_response_no_internal_id():
    """急诊响应不暴露系统字段。"""
    from medical_agent.emergency import build_emergency_response, detect_emergency

    is_em, matched = detect_emergency("突然胸痛")
    response = build_emergency_response(matched)
    # 不应有 schedule_id、patient_id、doctor_id 等
    assert "schedule_id" not in response
    assert "patient_id" not in response
    assert "doctor_id" not in response


def test_empty_text_no_emergency():
    """空文本不触发急诊。"""
    from medical_agent.emergency import detect_emergency

    is_em, matched = detect_emergency("")
    assert is_em is False
    assert matched == []
