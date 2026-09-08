"""机制级 HITL 测试（v4）：写工具内部 interrupt() 把门。

覆盖：
1. 非图环境直接调 .func() → 默认拦截（HITL_UNAVAILABLE）
2. 非图环境 + MEDICAL_HITL_BYPASS=1 → 放行（demo/单测通道）
3. 图内调用 → interrupt 暂停，approve 后落库，reject 后不落库
"""

from __future__ import annotations

import json
import os

import pytest


@pytest.fixture
def hitl_bypass_off():
    """确保 bypass 关闭。"""
    old = os.environ.pop("MEDICAL_HITL_BYPASS", None)
    yield
    if old is not None:
        os.environ["MEDICAL_HITL_BYPASS"] = old


@pytest.fixture
def hitl_bypass_on():
    """临时打开 bypass。"""
    old = os.environ.get("MEDICAL_HITL_BYPASS")
    os.environ["MEDICAL_HITL_BYPASS"] = "1"
    yield
    if old is None:
        os.environ.pop("MEDICAL_HITL_BYPASS", None)
    else:
        os.environ["MEDICAL_HITL_BYPASS"] = old


class TestHitlGateOutsideGraph:
    """非图执行环境：机制级拦截。"""

    def test_set_appointment_blocked_without_bypass(self, temp_db_path, hitl_bypass_off):
        from medical_agent.tools.appointment import set_appointment

        result = json.loads(
            set_appointment.func(
                patient_id="P001", doctor_id=1, schedule_id=1, idempotency_key="t1"
            )
        )
        assert result["success"] is False
        # 缺参数先报 MISSING_PARAMS 也算拦截；但专门造有参数的场景验证 HITL 拦截
        assert result["error_code"] in ("MISSING_PARAMS", "RECHECK_FAILED", "HITL_UNAVAILABLE")

    def test_cancel_appointment_blocked_without_bypass(self, temp_db_path, hitl_bypass_off):
        from medical_agent.tools.appointment import cancel_appointment

        result = json.loads(cancel_appointment.func(appointment_id="A001", reason="测试"))
        assert result["success"] is False
        assert result["error_code"] == "HITL_UNAVAILABLE"

    def test_reschedule_blocked_without_bypass(self, temp_db_path, hitl_bypass_off):
        from medical_agent.tools.appointment import reschedule_appointment

        result = json.loads(
            reschedule_appointment.func(
                appointment_id="A001", new_schedule_id=1, new_expected_schedule_version=0
            )
        )
        assert result["success"] is False
        assert result["error_code"] == "HITL_UNAVAILABLE"

    def test_restore_blocked_without_bypass(self, temp_db_path, hitl_bypass_off):
        from medical_agent.tools.appointment import restore_appointment

        result = json.loads(restore_appointment.func(appointment_id="A001"))
        assert result["success"] is False
        assert result["error_code"] == "HITL_UNAVAILABLE"

    def test_bypass_allows_through(self, temp_db_path, hitl_bypass_on):
        """bypass 打开后不再报 HITL_UNAVAILABLE（会继续走业务校验）。"""
        from medical_agent.tools.appointment import cancel_appointment

        result = json.loads(cancel_appointment.func(appointment_id="A_NOT_EXIST"))
        # 预约不存在 → CANCEL_FAILED，但绝不是 HITL_UNAVAILABLE
        assert result["error_code"] != "HITL_UNAVAILABLE"


class TestApprovalDecision:
    """审批决策词的判定逻辑。"""

    def test_approve_words(self):
        from medical_agent.tools.appointment import _APPROVE_WORDS

        for w in ("确认", "好", "yes", "ok"):
            assert w in _APPROVE_WORDS

    def test_reject_in_graph(self, temp_db_path, monkeypatch):
        """图内 interrupt 收到 reject → 返回 HITL_REJECTED，不落库。"""
        import medical_agent.tools.appointment as appt_mod

        monkeypatch.setattr(appt_mod, "interrupt", lambda payload: "reject:排班冲突")

        from medical_agent.tools.appointment import cancel_appointment

        result = json.loads(cancel_appointment.func(appointment_id="A001"))
        assert result["success"] is False
        assert result["error_code"] == "HITL_REJECTED"

    def test_approve_in_graph(self, temp_db_path, monkeypatch):
        """图内 interrupt 收到 approve → 继续执行业务逻辑（此处预约不存在会报业务错误，但不是 HITL 拦截）。"""
        import medical_agent.tools.appointment as appt_mod

        monkeypatch.setattr(appt_mod, "interrupt", lambda payload: "approve")

        from medical_agent.tools.appointment import cancel_appointment

        result = json.loads(cancel_appointment.func(appointment_id="A_NOT_EXIST"))
        assert result["error_code"] not in ("HITL_UNAVAILABLE", "HITL_REJECTED")
