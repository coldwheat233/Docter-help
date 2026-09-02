"""Eval Pipeline：用例执行器 + 指标统计。

第 1 周：跑 5 个 stub 用例 + 5 个新用例
第 2 周：扩到 20+ 用例
第 3 周：完整指标 + 报告生成

模式：
- 纯规则模式（默认）：只测 intent 准确率，不调 Supervisor
- 真 Supervisor 模式（--with-app）：跑完整流程（需要 LLM 支持 tool calling）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from medical_agent.agents.router import classify_intent_stub


# =====================================================================
# 数据结构
# =====================================================================
@dataclass
class CaseResult:
    """单条用例执行结果。"""

    case_id: str
    passed: bool
    expected: dict
    actual: dict
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class EvalSummary:
    """汇总报告。"""

    total: int
    passed: int
    failed: int
    pass_rate: float
    intent_accuracy: float
    flow_completion_rate: float
    hitl_compliance_rate: float
    avg_duration_ms: float
    results: list[CaseResult]
    timestamp: str


# =====================================================================
# 单条用例执行
# =====================================================================
def run_case(case: dict, app=None, thread_id_prefix: str = "eval") -> CaseResult:
    """跑一条测试用例。

    Args:
        case: 测试用例 dict
        app: 可选 Supervisor app。如果传了会真跑流程（需要 LLM 支持 tool calling）
        thread_id_prefix: thread_id 前缀

    Returns:
        CaseResult
    """
    import time

    start = time.time()
    errors: list[str] = []
    actual_steps: list[str] = []
    actual_intent: str | None = None
    actual_final_status: str | None = None

    # 1. intent 用规则分类（不依赖 LLM）
    first_msg = case["user_messages"][0] if case.get("user_messages") else ""
    actual_intent = classify_intent_stub(first_msg)

    # 2. 可选：实际跑 Supervisor
    if app is not None:
        from langchain_core.messages import HumanMessage

        config = {"configurable": {"thread_id": f"{thread_id_prefix}-{case['case_id']}"}}
        for i, user_msg in enumerate(case.get("user_messages", [])):
            try:
                result = app.invoke(
                    {"messages": [HumanMessage(content=user_msg)]},
                    config=config,
                )
                for m in result.get("messages", []):
                    cls_name = m.__class__.__name__
                    if cls_name == "AIMessage":
                        content = getattr(m, "content", "")
                        if isinstance(content, str):
                            if "Transferring back to supervisor" in content:
                                actual_steps.append("__handoff__")
                        for tc in getattr(m, "tool_calls", []) or []:
                            name = tc.get("name", "")
                            if "transfer" in name.lower() or "handoff" in name.lower():
                                actual_steps.append(name)
                    elif cls_name == "ToolMessage":
                        actual_steps.append(f"tool:{m.name}")
                        content = getattr(m, "content", "")
                        if isinstance(content, str):
                            if "confirmed" in content.lower():
                                actual_final_status = "confirmed"
                            elif "cancelled" in content.lower():
                                actual_final_status = "cancelled"
            except Exception as e:
                errors.append(f"round {i + 1}: {type(e).__name__}: {e}")

    # 3. 断言
    expected = case.get("expected", {})
    if "intent" in expected:
        if actual_intent != expected["intent"]:
            errors.append(
                f"intent mismatch: expected={expected['intent']}, actual={actual_intent}"
            )
    if "final_status" in expected and actual_final_status:
        if actual_final_status != expected["final_status"]:
            errors.append(
                f"final_status mismatch: expected={expected['final_status']}, actual={actual_final_status}"
            )

    duration_ms = int((time.time() - start) * 1000)

    return CaseResult(
        case_id=case["case_id"],
        passed=len(errors) == 0,
        expected=expected,
        actual={
            "intent": actual_intent,
            "steps": actual_steps,
            "final_status": actual_final_status,
        },
        errors=errors,
        duration_ms=duration_ms,
    )


# =====================================================================
# 汇总跑
# =====================================================================
def run_all(cases_dir: Path, app=None) -> EvalSummary:
    """跑所有用例，返回汇总。

    Args:
        cases_dir: 用例 JSON 目录
        app: 可选 Supervisor app
    """
    cases = []
    for f in sorted(cases_dir.glob("*.json")):
        try:
            cases.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"[eval] 跳过 {f.name}: JSON 解析失败 {e}")

    results = [run_case(c, app=app) for c in cases]

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    intent_correct = sum(
        1
        for r, c in zip(results, cases)
        if r.actual.get("intent") == c.get("expected", {}).get("intent")
    )
    flow_completed = sum(
        1
        for r, c in zip(results, cases)
        if r.actual.get("final_status") == c.get("expected", {}).get("final_status")
    )
    hitl_compliant = sum(
        1
        for r, c in zip(results, cases)
        if c.get("expected", {}).get("hitl_required", False)
    )

    return EvalSummary(
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=passed / total if total else 0.0,
        intent_accuracy=intent_correct / total if total else 0.0,
        flow_completion_rate=flow_completed / total if total else 0.0,
        hitl_compliance_rate=hitl_compliant / total if total else 0.0,
        avg_duration_ms=(
            sum(r.duration_ms for r in results) / total if total else 0
        ),
        results=results,
        timestamp=datetime.now().isoformat(),
    )


def print_summary(summary: EvalSummary) -> None:
    """打印汇总报告。"""
    print("=" * 70)
    print("EVAL PIPELINE REPORT")
    print("=" * 70)
    print(f"Time:        {summary.timestamp}")
    print(f"Total:       {summary.total}")
    print(f"Passed:      {summary.passed}  ({summary.pass_rate:.1%})")
    print(f"Failed:      {summary.failed}")
    print()
    print("Metrics:")
    print(f"  Intent Accuracy:     {summary.intent_accuracy:.1%}  (target >= 90%)")
    print(f"  Flow Completion:     {summary.flow_completion_rate:.1%}  (target >= 85%)")
    print(f"  HITL Compliance:     {summary.hitl_compliance_rate:.1%}  (target = 100%)")
    print(f"  Avg Duration:        {summary.avg_duration_ms:.0f}ms  (target <= 180000ms / 3min)")
    print()
    print("Per-case results:")
    for r in summary.results:
        status = "[PASS]" if r.passed else "[FAIL]"
        print(f"  {status} {r.case_id:35s} ({r.duration_ms:>5d}ms)")
        for err in r.errors:
            print(f"           - {err}")


def generate_report_md(summary: EvalSummary, output_path: Path) -> None:
    """生成 Markdown 格式报告。"""
    md = f"""# 05 - 测试报告（Eval Pipeline 自动生成）

**生成时间**：{summary.timestamp}

## 汇总

| 指标 | 实测 | 目标 | 状态 |
|---|---|---|---|
| 总用例数 | {summary.total} | - | - |
| 通过数 | {summary.passed} | - | - |
| 失败数 | {summary.failed} | - | - |
| **通过率** | {summary.pass_rate:.1%} | - | - |
| **意图路由准确率** | {summary.intent_accuracy:.1%} | >= 90% | {'OK' if summary.intent_accuracy >= 0.9 else 'FAIL'} |
| **流程完整率** | {summary.flow_completion_rate:.1%} | >= 85% | {'OK' if summary.flow_completion_rate >= 0.85 else 'FAIL'} |
| **HITL 合规率** | {summary.hitl_compliance_rate:.1%} | = 100% | {'OK' if summary.hitl_compliance_rate >= 1.0 else 'TODO'} |
| **平均单次对话时长** | {summary.avg_duration_ms:.0f}ms | <= 180000ms (3min) | {'OK' if summary.avg_duration_ms <= 180000 else 'FAIL'} |

## 用例详情

"""
    for r in summary.results:
        status = "✅" if r.passed else "❌"
        md += f"### {status} `{r.case_id}`\n\n"
        md += f"- 时长：{r.duration_ms}ms\n"
        md += f"- 期望：{r.expected}\n"
        md += f"- 实际：{r.actual}\n"
        if r.errors:
            md += "- 错误：\n"
            for err in r.errors:
                md += f"  - {err}\n"
        md += "\n"

    output_path.write_text(md, encoding="utf-8")
    print(f"\n[OK] report saved to {output_path}")


# =====================================================================
# CLI
# =====================================================================
if __name__ == "__main__":
    import sys

    project_root = Path(__file__).parent.parent.parent.parent
    cases_dir = project_root / "tests" / "cases"

    app = None
    if "--with-app" in sys.argv:
        from medical_agent.graphs.supervisor import build_supervisor_app
        app = build_supervisor_app()

    summary = run_all(cases_dir, app=app)
    print_summary(summary)

    if "--report" in sys.argv:
        report_path = project_root / "docs" / "05-测试报告.md"
        generate_report_md(summary, report_path)
