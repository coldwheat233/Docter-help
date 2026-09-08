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
    hitl_interrupted: bool = False
    """真实跑到了 interrupt 审批点（HITL 机制生效的证据）"""


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
def _patient_appointments(patient_id: str) -> list[dict]:
    """直接查 DB：某患者的全部预约（真实落库状态，比扫消息可靠）。"""
    from medical_agent.db.database import get_db

    db = get_db()
    cur = db.execute(
        "SELECT id, status, schedule_id FROM appointments WHERE patient_id = ? ORDER BY rowid",
        (patient_id,),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        try:
            out.append(dict(r))
        except (TypeError, ValueError):
            out.append({"id": r[0], "status": r[1], "schedule_id": r[2]})
    return out


def _seed_appointment_for_case(patient_id: str) -> str | None:
    """为 cancel/reschedule 用例预置一条真实预约（绕过 HITL，模拟历史数据）。

    Returns:
        预约单号；失败返回 None
    """
    import os

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import ScheduleRepository
    from medical_agent.tools.appointment import set_appointment

    db = get_db()
    schedules = ScheduleRepository(db).find_available(
        department="消化科",
        start_date=__import__("datetime").date.today(),
        end_date=__import__("datetime").date.today() + __import__("datetime").timedelta(days=7),
    )
    if not schedules:
        return None
    s = schedules[0]
    old = os.environ.get("MEDICAL_HITL_BYPASS")
    os.environ["MEDICAL_HITL_BYPASS"] = "1"
    try:
        result = json.loads(
            set_appointment.func(
                patient_id=patient_id,
                doctor_id=s["doctor_id"],
                schedule_id=s["schedule_id"],
                expected_schedule_version=s["schedule_version"],
                idempotency_key=f"eval-seed-{patient_id}-{s['schedule_id']}",
                symptoms="eval 预置预约",
            )
        )
    finally:
        if old is None:
            os.environ.pop("MEDICAL_HITL_BYPASS", None)
        else:
            os.environ["MEDICAL_HITL_BYPASS"] = old
    return result.get("appointment_id") if result.get("success") else None


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
    hitl_interrupted = False

    # 1. intent 用规则分类（不依赖 LLM）
    first_msg = case["user_messages"][0] if case.get("user_messages") else ""
    actual_intent = classify_intent_stub(first_msg)

    # 2. 可选：实际跑 Supervisor
    if app is not None:
        from langchain_core.messages import HumanMessage

        from medical_agent.graphs.hitl import get_pending_interrupt, resume_with_decision

        config = {"configurable": {"thread_id": f"{thread_id_prefix}-{case['case_id']}"}}
        # 模拟登录态注入 patient_id（对齐 Web 端真实行为）
        patient_id = case.get("patient_id", "P20240001")
        expected = case.get("expected", {})

        # cancel/reschedule 类用例：预置一条真实预约（否则没有可取消/可改约的对象）
        seeded_appointment_id: str | None = None
        seeded_schedule_id: int | None = None
        if expected.get("intent") in ("cancel", "reschedule"):
            seeded_appointment_id = _seed_appointment_for_case(patient_id)
            if seeded_appointment_id:
                for a in _patient_appointments(patient_id):
                    if a["id"] == seeded_appointment_id:
                        seeded_schedule_id = a["schedule_id"]
                # 把预约号告诉"用户"，模拟真实场景（用户知道自己有预约）
                # 不改 case 文件，追加为首条消息的上下文
            else:
                errors.append("预置预约失败（无可用排班）")

        before_ids = {a["id"] for a in _patient_appointments(patient_id)}

        # book 类用例补两句："选第一个" → "确认"（对齐真实 UX：先选定时段，复述后再确认落库）
        user_msgs = list(case.get("user_messages", []))
        if expected.get("final_status") == "confirmed" and expected.get("intent") == "book":
            if not any("确认" in m for m in user_msgs):
                user_msgs.extend(["就选第一个吧", "确认"])
        if seeded_appointment_id and user_msgs:
            user_msgs[0] = f"{user_msgs[0]}（我的预约号是 {seeded_appointment_id}）"
        for i, user_msg in enumerate(user_msgs):
            try:
                result = app.invoke(
                    {
                        "messages": [HumanMessage(content=user_msg)],
                        "patient_id": patient_id,
                    },
                    config=config,
                )
                # HITL：图暂停在写工具 interrupt 时自动 approve（模拟审核员）
                # 最多批 5 次，防死循环
                for _ in range(5):
                    intr = get_pending_interrupt(app, config)
                    if intr is None:
                        break
                    hitl_interrupted = True
                    actual_steps.append("hitl_interrupt")
                    result = resume_with_decision(app, config, "approve")
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
            except Exception as e:
                errors.append(f"round {i + 1}: {type(e).__name__}: {e}")

        # final_status 真实判定：查 DB，不扫消息
        appts_after = _patient_appointments(patient_id)
        new_appts = [a for a in appts_after if a["id"] not in before_ids]
        intent = expected.get("intent")
        if intent == "book":
            if any(a["status"] == "confirmed" for a in new_appts):
                actual_final_status = "confirmed"
            elif not errors:
                # 发起了预约但未走完（如信息不全被反问）→ intake_in_progress
                actual_final_status = "intake_in_progress"
        elif intent == "cancel" and seeded_appointment_id:
            for a in appts_after:
                if a["id"] == seeded_appointment_id and a["status"] == "cancelled":
                    actual_final_status = "cancelled"
        elif intent == "reschedule" and seeded_appointment_id:
            for a in appts_after:
                if a["id"] == seeded_appointment_id and a["schedule_id"] != seeded_schedule_id:
                    actual_final_status = "confirmed"  # 改约成功，状态保持 confirmed
        elif intent == "consult":
            # 咨询类：流程没报错、有正常回复即视为 answered
            if not errors:
                actual_final_status = "answered"

    # 3. 断言
    expected = case.get("expected", {})
    if "intent" in expected:
        if actual_intent != expected["intent"]:
            errors.append(
                f"intent mismatch: expected={expected['intent']}, actual={actual_intent}"
            )
    # final_status 只在真跑 app 时断言（规则模式没跑流程，不应误报通过/失败）
    if app is not None and "final_status" in expected:
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
        hitl_interrupted=hitl_interrupted,
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
    # 流程完整率只统计声明了 final_status 的用例（避免 None==None 假阳性）
    flow_cases = [
        (r, c) for r, c in zip(results, cases) if c.get("expected", {}).get("final_status")
    ]
    flow_completed = sum(
        1
        for r, c in flow_cases
        if r.actual.get("final_status") == c.get("expected", {}).get("final_status")
    )
    hitl_required_cases = [
        (r, c)
        for r, c in zip(results, cases)
        if c.get("expected", {}).get("hitl_required", False)
    ]
    # HITL 合规率 = 声明需要人工确认的用例中，真实触发了 interrupt 审批点的比例
    # （旧算法只数标记数量，是假指标；v4 起机制级 interrupt 可实测）
    hitl_compliant = sum(1 for r, _ in hitl_required_cases if r.hitl_interrupted)

    return EvalSummary(
        total=total,
        passed=passed,
        failed=total - passed,
        pass_rate=passed / total if total else 0.0,
        intent_accuracy=intent_correct / total if total else 0.0,
        flow_completion_rate=flow_completed / len(flow_cases) if flow_cases else 0.0,
        hitl_compliance_rate=(
            hitl_compliant / len(hitl_required_cases) if hitl_required_cases else 0.0
        ),
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
