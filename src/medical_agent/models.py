"""Pydantic 模型：所有 IO 强类型 + 业务规则约束。

第 3 周：从 TypedDict 升级到 Pydantic BaseModel。
- State: AppointmentState / IntakeState
- Tool 输入: SetAppointmentInput / CancelAppointmentInput / ...
- 业务模型: SymptomReport / TimeSlot / AppointmentResult
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# =====================================================================
# 枚举
# =====================================================================
class IntentType(str, Enum):
    CONSULT = "consult"
    BOOK = "book"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class TimeSlot(str, Enum):
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"


class AppointmentStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


# =====================================================================
# 业务模型
# =====================================================================
class SymptomReport(BaseModel):
    """问诊信息收集结果。"""

    symptoms: Optional[str] = Field(None, max_length=500, description="主诉症状")
    duration: Optional[str] = Field(None, max_length=100, description="病程")
    severity: Optional[Severity] = Field(None, description="严重程度")
    department: Optional[str] = Field(None, max_length=50, description="推荐科室")

    @field_validator("department")
    @classmethod
    def validate_department(cls, v: str | None) -> str | None:
        """科室必须在白名单内。"""
        if v is None:
            return v
        allowed = {"心内科", "消化科", "儿科", "骨科", "皮肤科"}
        if v not in allowed:
            raise ValueError(f"科室 {v} 不在白名单 {allowed} 内")
        return v


class TimeSlotInfo(BaseModel):
    """排班时段信息。"""

    schedule_id: int = Field(..., ge=1, description="排班 ID（内部字段）")
    doctor_id: int = Field(..., ge=1, description="医生 ID（内部字段）")
    schedule_version: int = Field(..., ge=0, description="乐观锁版本号（内部字段）")
    doctor_name: str = Field(..., min_length=1, description="医生姓名（展示用）")
    doctor_title: str = Field("主治医师", description="医生职称（展示用）")
    department: str = Field(..., description="科室（展示用）")
    schedule_date: date = Field(..., description="日期（展示用）")
    time_slot: TimeSlot = Field(..., description="时段（展示用）")
    start_time: str = Field(..., description="开始时间（展示用）")
    end_time: str = Field(..., description="结束时间（展示用）")
    remaining: int = Field(..., ge=0, description="剩余号源")


class AppointmentResult(BaseModel):
    """预约结果。"""

    success: bool
    appointment_id: Optional[str] = Field(None, description="预约号（成功时有）")
    status: Optional[AppointmentStatus] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None

    def to_user_message(self) -> str:
        """转成给用户看的中文消息（过滤内部 ID）。"""
        if self.success:
            return (
                f"✅ 预约成功！\n"
                f"预约号：{self.appointment_id}\n"
                f"状态：已确认"
            )
        return (
            f"❌ 预约失败\n"
            f"原因：{self.error_message or '未知错误'}"
        )


# =====================================================================
# Tool 输入模型（强类型 + 业务规则）
# =====================================================================
class SetAppointmentInput(BaseModel):
    """set_appointment 工具输入。

    所有参数可选（从 state 推断），但若传了必须合法。
    """

    patient_id: str = Field("", min_length=0, max_length=20)
    doctor_id: int = Field(0, ge=0)
    schedule_id: int = Field(0, ge=0)
    expected_schedule_version: int = Field(0, ge=0)
    idempotency_key: str = Field("", max_length=100)
    symptoms: str = Field("", max_length=500)
    duration: str = Field("", max_length=100)
    severity: str = Field("", max_length=20)

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v and v not in {s.value for s in Severity}:
            raise ValueError(f"severity 必须是 mild/moderate/severe，当前 {v}")
        return v


class CancelAppointmentInput(BaseModel):
    """cancel_appointment 工具输入。"""

    appointment_id: str = Field(..., min_length=1, max_length=30, description="预约号")
    reason: str = Field("", max_length=200, description="取消原因")


class CheckAvailabilityInput(BaseModel):
    """check_availability 工具输入。"""

    department: str = Field(..., min_length=1, max_length=50)
    start_date: date
    end_date: Optional[date] = None
    time_slot: Optional[TimeSlot] = None


# =====================================================================
# State 模型
# =====================================================================
class AppointmentStateModel(BaseModel):
    """完整的预约 State（Pydantic 版）。

    与 LangGraph 集成：
    - LangGraph 0.3+ 支持 Pydantic state schema
    - 用 `add_messages` reducer 处理 messages
    - 字段强类型 + 业务规则
    """

    # 消息历史
    from langgraph.graph.message import add_messages
    messages: list = Field(default_factory=list)

    # 用户身份
    patient_id: Optional[str] = Field(None, max_length=20)

    # 原始查询
    raw_query: Optional[str] = Field(None, max_length=500)

    # 路由
    intent: Optional[IntentType] = None

    # 问诊信息（嵌套 Pydantic 模型）
    symptoms: Optional[str] = Field(None, max_length=500)
    duration: Optional[str] = Field(None, max_length=100)
    severity: Optional[Severity] = None
    department: Optional[str] = Field(None, max_length=50)

    # 排班
    preferred_date: Optional[date] = None
    preferred_time_slot: Optional[TimeSlot] = None
    recommended_slots: list[TimeSlotInfo] = Field(default_factory=list)
    selected_slot: Optional[TimeSlotInfo] = None

    # 流程控制
    current_step: str = Field("init", description="init/intake/schedule/confirm/done")
    pending_human_confirm: bool = False

    # 输出
    appointment_id: Optional[str] = Field(None, max_length=30)
    status: Optional[AppointmentStatus] = None
    final_answer: Optional[str] = Field(None, max_length=2000)

    class Config:
        """Pydantic 配置。"""

        # 允许任意类型（兼容 LangGraph 的消息对象）
        arbitrary_types_allowed = True
        # 允许字段别名
        populate_by_name = True

    @field_validator("current_step")
    @classmethod
    def validate_step(cls, v: str) -> str:
        allowed = {"init", "intake", "schedule", "confirm", "done"}
        if v not in allowed:
            raise ValueError(f"current_step 必须是 {allowed} 之一，当前 {v}")
        return v

    @field_validator("department")
    @classmethod
    def validate_department(cls, v: str | None) -> str | None:
        if v is None:
            return v
        allowed = {"心内科", "消化科", "儿科", "骨科", "皮肤科"}
        if v not in allowed:
            raise ValueError(f"科室 {v} 不在白名单 {allowed} 内")
        return v


# =====================================================================
# LangGraph 集成（add_messages reducer + state schema）
# =====================================================================
from typing import Annotated
from langgraph.graph.message import add_messages


def make_langgraph_state():
    """构造 LangGraph 用的 Annotated state（用 add_messages reducer）。"""
    return Annotated[AppointmentStateModel, add_messages]
