"""FastAPI 后端：React 前端的 API 层。

保留原有 LangGraph 链路不动，这里只做 HTTP 包装：
- 护栏 / 急诊短路 / 限流 复用 web/app.py 同款逻辑
- HITL：chat 返回 pending_approval → 前端渲染审批卡 → POST /api/approve resume

启动：
    python web/api.py
    # 或 uvicorn web.api:app --port 8000 --reload

接口：
- POST /api/chat         {thread_id, patient_id, message}
- POST /api/approve      {thread_id, decision}          decision: "approve" | "reject:原因"
- GET  /api/appointments?patient_id=P20240001
- GET  /api/appointments/{appointment_id}
- GET  /api/departments
- GET  /api/health
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="医疗预约助手 API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境放开；生产收紧
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局单例 app（checkpointer 按 thread_id 隔离会话）
_graph_app = None


def get_graph_app():
    global _graph_app
    if _graph_app is None:
        from medical_agent.graphs.supervisor import build_supervisor_app

        _graph_app = build_supervisor_app()
    return _graph_app


# =====================================================================
# 请求/响应模型
# =====================================================================
class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    patient_id: str = "P20240001"


class ApproveRequest(BaseModel):
    thread_id: str
    decision: str  # "approve" | "reject:原因"


class ChatResponse(BaseModel):
    thread_id: str
    messages: list[dict[str, Any]]
    pending_approval: dict[str, Any] | None = None
    blocked: bool = False


# =====================================================================
# 工具函数
# =====================================================================
def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _msg_count(graph_app, thread_id: str) -> int:
    try:
        snap = graph_app.get_state(_config(thread_id))
        return len(snap.values.get("messages", []))
    except Exception:
        return 0


def _new_messages(graph_app, thread_id: str, since: int) -> list[dict[str, Any]]:
    """取出 since 之后的新消息，序列化成前端友好格式。"""
    try:
        snap = graph_app.get_state(_config(thread_id))
        msgs = snap.values.get("messages", [])
    except Exception:
        return []
    out = []
    for m in msgs[since:]:
        cls = m.__class__.__name__
        content = getattr(m, "content", "")
        if not isinstance(content, str):
            content = "".join(c for c in content if isinstance(c, str)) if isinstance(content, list) else str(content)
        if cls == "HumanMessage":
            out.append({"role": "user", "content": content})
        elif cls == "AIMessage" and content.strip():
            out.append({
                "role": "assistant",
                "content": content,
                "agent": getattr(m, "name", "") or "",
            })
        elif cls == "ToolMessage":
            # 写工具结果（含成功/失败 JSON）转成结构化事件，其余工具结果不回显
            try:
                parsed = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict) and "success" in parsed:
                out.append({"role": "tool_result", "content": content, "data": parsed})
    return out


def _pending_approval(graph_app, thread_id: str) -> dict[str, Any] | None:
    from medical_agent.graphs.hitl import get_pending_interrupt

    intr = get_pending_interrupt(graph_app, _config(thread_id))
    if intr is None:
        return None
    payload = getattr(intr, "value", intr)
    return payload if isinstance(payload, dict) else {"detail": str(payload)}


def _sanitize_messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """输出侧护栏：assistant 消息若泄露系统提示词，替换为统一拒绝话术。"""
    from medical_agent.guardrails import check_output

    out = []
    for m in msgs:
        if m.get("role") == "assistant":
            gr = check_output(m.get("content", ""))
            if not gr.is_safe and gr.category == "leak":
                m = {
                    **m,
                    "content": "抱歉，我只能协助您处理预约挂号相关的问题。",
                    "leak_blocked": True,
                }
        out.append(m)
    return out


# =====================================================================
# 接口
# =====================================================================
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "medical-appointment-agent"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    from langchain_core.messages import HumanMessage

    thread_id = req.thread_id or f"web-{uuid.uuid4().hex[:12]}"
    text = req.message.strip()
    if not text:
        return ChatResponse(thread_id=thread_id, messages=[])

    # 1) 输入护栏
    from medical_agent.guardrails import check_input

    gr = check_input(text)
    if not gr.is_safe:
        return ChatResponse(
            thread_id=thread_id,
            messages=[
                {"role": "user", "content": text},
                {"role": "assistant", "content": f"🛡️ {gr.reason}", "agent": "guardrail"},
            ],
            blocked=True,
        )

    # 2) 急诊短路（不调 LLM，立即返回 120 指引）
    from medical_agent.emergency import build_emergency_response, detect_emergency

    is_em, matched = detect_emergency(text)
    if is_em:
        return ChatResponse(
            thread_id=thread_id,
            messages=[
                {"role": "user", "content": text},
                {"role": "assistant", "content": build_emergency_response(matched), "agent": "emergency"},
            ],
        )

    # 3) 限流
    from medical_agent.rate_limit import check_rate_limit

    allowed, limit_info = check_rate_limit(req.patient_id)
    if not allowed:
        return ChatResponse(
            thread_id=thread_id,
            messages=[
                {"role": "user", "content": text},
                {
                    "role": "assistant",
                    "content": f"⏳ 系统繁忙，请 {limit_info.get('retry_after', 60)} 秒后再试。",
                    "agent": "rate_limit",
                },
            ],
            blocked=True,
        )

    # 4) 走 LangGraph 链路
    graph_app = get_graph_app()
    before = _msg_count(graph_app, thread_id)
    graph_app.invoke(
        {"messages": [HumanMessage(content=text)], "patient_id": req.patient_id},
        config=_config(thread_id),
    )

    return ChatResponse(
        thread_id=thread_id,
        messages=_sanitize_messages(_new_messages(graph_app, thread_id, before)),
        pending_approval=_pending_approval(graph_app, thread_id),
    )


@app.post("/api/approve", response_model=ChatResponse)
def approve(req: ApproveRequest) -> ChatResponse:
    from medical_agent.graphs.hitl import resume_with_decision

    graph_app = get_graph_app()
    before = _msg_count(graph_app, req.thread_id)
    resume_with_decision(graph_app, _config(req.thread_id), req.decision)

    return ChatResponse(
        thread_id=req.thread_id,
        messages=_sanitize_messages(_new_messages(graph_app, req.thread_id, before)),
        pending_approval=_pending_approval(graph_app, req.thread_id),
    )


@app.get("/api/appointments")
def list_appointments(patient_id: str = "P20240001") -> dict:
    from medical_agent.tools.appointment_query import query_my_appointments

    class _RT:
        state = {"patient_id": patient_id}

    return json.loads(query_my_appointments.func(runtime=_RT(), limit=20))


@app.get("/api/appointments/{appointment_id}")
def appointment_detail(appointment_id: str, patient_id: str = "P20240001") -> dict:
    from medical_agent.tools.appointment_query import get_appointment_detail

    class _RT:
        state = {"patient_id": patient_id}

    return json.loads(get_appointment_detail.func(appointment_id=appointment_id, runtime=_RT()))


@app.get("/api/departments")
def departments() -> dict:
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DepartmentRepository

    return {"departments": DepartmentRepository(get_db()).list_all()}


# =====================================================================
# 静态托管 React build 产物（web-react/dist 存在时）
# =====================================================================
DIST_DIR = PROJECT_ROOT / "web-react" / "dist"
if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> Any:
        if full_path.startswith("api/"):
            return {"error": "not found"}
        return FileResponse(DIST_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
