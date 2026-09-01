"""多智能体共享的 State 定义。

设计原则：
- 用 TypedDict 而不是 BaseModel：与 LangGraph 原生 StateGraph 兼容
- 所有字段都有注释，标 [input]/[output]/[internal]
- 字段值用 None 表示"未收集"，区分"用户明确回答为空"
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


# =====================================================================
# 意图枚举
# =====================================================================
IntentType = Literal["consult", "book", "reschedule", "cancel", "unknown"]
"""4 类意图：咨询 / 预约 / 改约 / 取消 / 未知"""

AppointmentStatus = Literal[
    "pending",      # 已收集信息，未确认
    "confirmed",    # 已落库
    "cancelled",    # 已取消
    "completed",    # 已就诊
    "no_show",      # 未到诊
]
"""预约状态机"""


# =====================================================================
# 顶层 State：贯穿全流程
# =====================================================================
class AppointmentState(TypedDict, total=False):
    """医疗预约对话的完整状态。

    字段分组：
    - 用户输入相关：messages / patient_id / raw_query
    - 问诊收集：symptoms / duration / severity / department
    - 排班：preferred_date / preferred_time_slot / recommended_slots / selected_slot
    - 流程控制：intent / current_step / pending_human_confirm
    - 输出：appointment_id / status / final_answer
    """

    # ---------- 消息历史（自动累加） ----------
    messages: Annotated[list[Any], add_messages]
    """对话消息列表，LangGraph 自动用 add_messages reducer 累加"""

    # ---------- 用户身份 ----------
    patient_id: str | None
    """患者 ID（[input]）。第 2 周接入用户系统"""

    # ---------- 原始查询 ----------
    raw_query: str | None
    """[input] 用户最新一条自然语言查询"""

    # ---------- 路由结果 ----------
    intent: IntentType
    """[output] 路由 Agent 输出的意图"""

    # ---------- 问诊信息收集 ----------
    symptoms: str | None
    """[output] 主诉症状（intake 抽取）"""
    duration: str | None
    """[output] 病程（如 '3 天'）"""
    severity: Literal["mild", "moderate", "severe"] | None
    """[output] 严重程度（intake 评估）"""
    department: str | None
    """[output] 科室（如 '心内科'）"""

    # ---------- 排班 ----------
    preferred_date: str | None
    """[input] 用户希望就诊日期（YYYY-MM-DD）"""
    preferred_time_slot: Literal["morning", "afternoon", "evening"] | None
    """[input] 偏好时段"""
    recommended_slots: list[dict[str, Any]]
    """[output] scheduler 推荐的可预约时段列表"""
    selected_slot: dict[str, Any] | None
    """[input] 用户选定的时段"""

    # ---------- 流程控制 ----------
    current_step: Literal[
        "init",          # 启动
        "intake",        # 收集问诊信息
        "schedule",      # 推荐时段
        "confirm",       # 等待人工确认
        "done",          # 完成
    ]
    """[internal] 当前流程阶段"""

    pending_human_confirm: bool
    """[internal] 是否在等人工确认（HITL 触发）"""

    # ---------- 落库结果 ----------
    appointment_id: str | None
    """[output] 预约单号（落库后回填）"""
    status: AppointmentStatus
    """[output] 当前状态"""
    final_answer: str | None
    """[output] 给用户的最终回复"""


# =====================================================================
# 中间 State：仅供某些子 Agent 内部使用
# =====================================================================
class IntakeState(TypedDict, total=False):
    """intake Agent 内部用：维护问诊轮次与已收集字段。"""

    messages: Annotated[list[Any], add_messages]
    collected_fields: dict[str, Any]
    """已抽取字段快照：symptoms / duration / severity / department"""
    next_question: str | None
    """如果字段未齐，下一句要问什么"""
    is_complete: bool
    """是否所有必填字段都收齐"""
