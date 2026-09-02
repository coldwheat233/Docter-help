"""Eval Pipeline 测试。"""

import json
import tempfile
from pathlib import Path

import pytest

# tests/ 的绝对路径（避免被 tests/__init__.py 误导）
TESTS_DIR = Path(__file__).resolve().parent
CASES_DIR = TESTS_DIR / "cases"


def test_eval_runner_imports():
    """Eval runner 能 import。"""
    from medical_agent.eval.runner import run_case, run_all, EvalSummary, CaseResult

    assert callable(run_case)
    assert callable(run_all)


def test_eval_summary_dataclass():
    """EvalSummary 数据结构。"""
    from medical_agent.eval.runner import EvalSummary

    s = EvalSummary(
        total=10,
        passed=9,
        failed=1,
        pass_rate=0.9,
        intent_accuracy=0.95,
        flow_completion_rate=0.85,
        hitl_compliance_rate=1.0,
        avg_duration_ms=1200.0,
        results=[],
        timestamp="2026-09-02T00:00:00",
    )
    assert s.pass_rate == 0.9
    assert s.intent_accuracy == 0.95


def test_run_case_simple_consultation():
    """跑一条简单咨询用例（仅测 intent，不跑 supervisor）。"""
    from medical_agent.eval.runner import run_case

    case = {
        "case_id": "test_consult",
        "user_messages": ["感冒发烧怎么办？"],
        "expected": {"intent": "consult"},
    }

    result = run_case(case, app=None, thread_id_prefix="test")
    assert result.actual["intent"] == "consult"
    assert result.passed is True


def test_run_case_appointment_intent():
    """预约类意图识别。"""
    from medical_agent.eval.runner import run_case

    case = {
        "case_id": "test_book",
        "user_messages": ["我想挂号"],
        "expected": {"intent": "book"},
    }
    result = run_case(case, app=None, thread_id_prefix="test")
    assert result.actual["intent"] == "book"
    assert result.passed is True


def test_run_case_cancel_intent():
    """取消意图识别。"""
    from medical_agent.eval.runner import run_case

    case = {
        "case_id": "test_cancel",
        "user_messages": ["帮我取消预约"],
        "expected": {"intent": "cancel"},
    }
    result = run_case(case, app=None, thread_id_prefix="test")
    assert result.actual["intent"] == "cancel"
    assert result.passed is True


def test_run_case_reschedule_intent():
    """改约意图识别。"""
    from medical_agent.eval.runner import run_case

    case = {
        "case_id": "test_reschedule",
        "user_messages": ["我想改个时间"],
        "expected": {"intent": "reschedule"},
    }
    result = run_case(case, app=None, thread_id_prefix="test")
    assert result.actual["intent"] == "reschedule"
    assert result.passed is True


def test_run_all_with_real_cases():
    """跑所有真实用例（5 + 15 = 20 条）。"""
    from medical_agent.eval.runner import run_all

    # 不传 app，只测 intent 准确率（mock LLM 跑 supervisor 会因 bind_tools 失败）
    summary = run_all(CASES_DIR)

    # 至少 20 条用例（5 旧 + 15 新）
    assert summary.total >= 20
    assert summary.intent_accuracy >= 0.5


def test_eval_metrics_meet_targets():
    """指标达到立项书要求。"""
    from medical_agent.eval.runner import run_all

    summary = run_all(CASES_DIR)

    # 规则分类应该 >= 80%（20 条覆盖所有 intent）
    assert summary.intent_accuracy >= 0.8, f"intent_accuracy {summary.intent_accuracy:.1%} < 80%"


def test_generate_report_md(tmp_path):
    """生成 markdown 报告。"""
    from medical_agent.eval.runner import (
        EvalSummary,
        generate_report_md,
    )

    summary = EvalSummary(
        total=20,
        passed=18,
        failed=2,
        pass_rate=0.9,
        intent_accuracy=0.95,
        flow_completion_rate=0.85,
        hitl_compliance_rate=1.0,
        avg_duration_ms=1500.0,
        results=[],
        timestamp="2026-09-02T00:00:00",
    )
    report_path = tmp_path / "report.md"
    generate_report_md(summary, report_path)

    content = report_path.read_text(encoding="utf-8")
    assert "测试报告" in content
    assert "意图路由准确率" in content
    assert "95.0%" in content


def test_case_json_files_valid():
    """所有 JSON 用例都能解析。"""
    for json_file in sorted(CASES_DIR.glob("*.json")):
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert "case_id" in data, f"{json_file.name} 缺 case_id"
        assert "user_messages" in data, f"{json_file.name} 缺 user_messages"
        assert isinstance(data["user_messages"], list)
        assert len(data["user_messages"]) > 0


def test_total_cases_count():
    """用例总数 20+。"""
    count = len(list(CASES_DIR.glob("*.json")))
    assert count >= 20, f"只有 {count} 个用例，应 >= 20"
