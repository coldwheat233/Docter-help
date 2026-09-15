"""FastAPI 后端：React 前端的 API 层（v5）。

保留原有 LangGraph 链路不动，这里只做 HTTP 包装：
- 启动预热：lifespan 里编译图 + 预载 embedding（首问不再冷启动）
- SSE 流式：/api/chat/stream 推送进度事件（白名单话术，不透传内部字段）
- 护栏 / 急诊短路 / 三层限流（IP + 用户 + 全局令牌桶 + 攻击黑名单）
- 用户体系：register/login 发 token，patient_id 来自登录态而非客户端自报
- HITL：写操作在图内 interrupt 暂停 → 中台 /api/admin/approvals/decision resume（患者端不暴露审批单）

启动：
    python web/api.py
    # 或 uvicorn web.api:app --port 8000 --reload

接口：
- POST /api/register     {username, password, name, phone?}
- POST /api/login        {username, password} → {token, patient_id, name}
- POST /api/chat         {message, thread_id?, token? | patient_id}
- POST /api/chat/stream  同上，SSE 流式（progress / messages / pending_approval / done）
- GET  /api/appointments?patient_id= 或 ?token=
- GET  /api/appointments/{appointment_id}
- GET  /api/departments
- GET  /api/health
- GET  /api/security/stats  限流/黑名单状态
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


# =====================================================================
# 图单例 + 启动预热
# =====================================================================
_graph_app = None


def get_graph_app():
    global _graph_app
    if _graph_app is None:
        from medical_agent.graphs.supervisor import build_supervisor_app

        _graph_app = build_supervisor_app()
    return _graph_app


def _warmup() -> None:
    """启动预热：编译图 + 建表 + 预载 embedding 模型（用户首问不卡冷启动）。"""
    t0 = time.time()
    try:
        from medical_agent.db.database import init_db

        init_db()  # 幂等建表（含 users 表）
    except Exception as e:
        print(f"[warmup] init_db failed: {e}")
    try:
        _ensure_staff_account()
    except Exception as e:
        print(f"[warmup] staff seed failed: {e}")
    try:
        get_graph_app()
        print(f"[warmup] graph compiled ({time.time() - t0:.1f}s)")
    except Exception as e:
        print(f"[warmup] graph build failed: {e}")
    try:
        t1 = time.time()
        from medical_agent.agents.dense_search import _pick_default_embedder

        emb = _pick_default_embedder()
        emb.embed_query("预热")  # 触发权重加载
        print(f"[warmup] embedder loaded ({time.time() - t1:.1f}s)")
    except Exception as e:
        print(f"[warmup] embedder preload skipped: {e}")


def _ensure_staff_account() -> None:
    """demo 环境自动补一个业务中台账号（无 staff 时创建）。生产应由 IdP 管理。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import PatientRepository

    db = get_db()
    if db.execute("SELECT 1 FROM users WHERE role = 'staff' LIMIT 1").fetchone():
        return
    username, password = "staff", "Staff123456"
    if db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        return
    synthetic_pid = "STAFF-OPS-001"  # staff 不代表患者，仅满足 FK
    PatientRepository(db).upsert(synthetic_pid, "门诊运营（中台）", "")
    salt = secrets.token_hex(8)
    db.execute(
        "INSERT INTO users (username, password_hash, salt, patient_id, role) VALUES (?, ?, ?, ?, 'staff')",
        (username, _hash_password(password, salt), salt, synthetic_pid),
    )
    db.commit()
    print(f"[warmup] demo staff account created: {username} / {password}")


@asynccontextmanager
async def lifespan(_: FastAPI):
    import asyncio

    # 放线程池跑，不阻塞端口监听
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _warmup)
    yield


app = FastAPI(title="医疗预约助手 API", version="5.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境放开；生产收紧
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# 三层限流 + 攻击黑名单
# =====================================================================
from medical_agent.rate_limit import RateLimiter  # noqa: E402

_ip_limiter = RateLimiter(max_requests=30, window_seconds=60)  # IP 层：30 次/分钟
_offenses: dict[str, deque] = defaultdict(deque)  # ip → 护栏拦截时间戳
_blacklist: dict[str, float] = {}  # ip → 解封时间戳
_security_lock = Lock()

OFFENSE_WINDOW = 600  # 10 分钟内
OFFENSE_THRESHOLD = 3  # 被护栏拦 3 次
BAN_SECONDS = 300  # 封 5 分钟


def _client_ip(request: Request) -> str:
    # 只信直连 IP；X-Forwarded-For 可被伪造，生产在反代层处理
    return request.client.host if request.client else "unknown"


def _check_ip_allowed(ip: str) -> JSONResponse | None:
    """IP 黑名单 + IP 限流。返回 None = 放行，否则 403/429。"""
    now = time.time()
    with _security_lock:
        banned_until = _blacklist.get(ip, 0)
        if now < banned_until:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "检测到异常行为，已临时限制访问",
                    "retry_after": int(banned_until - now) + 1,
                },
            )
    allowed, info = _ip_limiter.is_allowed(ip)
    if not allowed:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(info["retry_after"])},
            content={"detail": "请求过于频繁，请稍后再试", "retry_after": info["retry_after"]},
        )
    return None


def _check_global_allowed() -> JSONResponse | None:
    """全局令牌桶（系统总容量保护）。"""
    from medical_agent.global_limiter import get_combined_limiter

    if not get_combined_limiter().global_limiter.try_acquire():
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": "1"},
            content={"detail": "系统繁忙，请稍后再试", "retry_after": 1},
        )
    return None


def _record_offense(ip: str) -> None:
    """护栏拦截计数：10 分钟内被拦 3 次 → 封 5 分钟。"""
    now = time.time()
    with _security_lock:
        dq = _offenses[ip]
        while dq and dq[0] < now - OFFENSE_WINDOW:
            dq.popleft()
        dq.append(now)
        if len(dq) >= OFFENSE_THRESHOLD:
            _blacklist[ip] = now + BAN_SECONDS
            dq.clear()
            print(f"[security] IP {ip} 触发护栏 {OFFENSE_THRESHOLD} 次，封禁 {BAN_SECONDS}s")


# =====================================================================
# 用户体系（demo 级：内存 session）
# =====================================================================
_sessions: dict[str, str] = {}  # token → patient_id
_sessions_lock = Lock()


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _resolve_patient_id(token: str | None, fallback: str) -> tuple[str, str | None]:
    """token → patient_id。返回 (patient_id, error)。staff 账号不能走患者接口。"""
    if token:
        sess = _get_session(token)
        if sess is None:
            return fallback, "token 无效或已过期，请重新登录"
        if sess.get("role") == "staff":
            return "", "这是业务中台账号，请使用患者账号登录"
        return sess["patient_id"], None
    return fallback, None


def _get_session(token: str) -> dict | None:
    with _sessions_lock:
        sess = _sessions.get(token)
    return dict(sess) if sess else None


def _staff_session(token: str | None, request: Request) -> dict | None:
    """中台鉴权：staff 登录 token 或 X-Admin-Token（运维）。通过返回身份，否则 None。"""
    if token:
        sess = _get_session(token)
        if sess and sess.get("role") == "staff":
            return {"role": "staff", "name": sess.get("name", "staff")}
    admin_token = os.environ.get("MEDICAL_ADMIN_TOKEN", "")
    if admin_token and request.headers.get("X-Admin-Token") == admin_token:
        return {"role": "admin", "name": "admin"}
    return None


class RegisterRequest(BaseModel):
    username: str
    password: str
    name: str
    phone: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/register")
def register(req: RegisterRequest, request: Request) -> Any:
    blocked = _check_ip_allowed(_client_ip(request))
    if blocked:
        return blocked
    from medical_agent.db.database import get_db, init_db
    from medical_agent.db.repositories import _APPT_WRITE_LOCK, PatientRepository

    db = get_db()
    patient_id = f"P{int(time.time() * 1000)}{secrets.randbelow(90) + 10}"
    # 共享 sqlite 连接：SELECT/INSERT/commit 全部在写锁内，防线程交错
    with _APPT_WRITE_LOCK:
        if db.execute("SELECT 1 FROM users WHERE username = ?", (req.username,)).fetchone():
            return JSONResponse(status_code=409, content={"detail": "用户名已存在"})
        PatientRepository(db).upsert(patient_id, req.name, req.phone)
        salt = secrets.token_hex(8)
        db.execute(
            "INSERT INTO users (username, password_hash, salt, patient_id) VALUES (?, ?, ?, ?)",
            (req.username, _hash_password(req.password, salt), salt, patient_id),
        )
        db.commit()

    token = secrets.token_urlsafe(24)
    with _sessions_lock:
        _sessions[token] = {"patient_id": patient_id, "name": req.name, "role": "patient"}
    return {"token": token, "patient_id": patient_id, "name": req.name, "role": "patient"}


@app.post("/api/login")
def login(req: LoginRequest, request: Request) -> Any:
    blocked = _check_ip_allowed(_client_ip(request))
    if blocked:
        return blocked
    from medical_agent.db.database import get_db

    db = get_db()
    row = db.execute(
        """SELECT u.password_hash, u.salt, u.patient_id, p.name, COALESCE(u.role, 'patient') AS role
           FROM users u LEFT JOIN patients p ON p.id = u.patient_id
           WHERE u.username = ?""",
        (req.username,),
    ).fetchone()
    if not row or row["password_hash"] != _hash_password(req.password, row["salt"]):
        return JSONResponse(status_code=401, content={"detail": "用户名或密码错误"})

    role = row["role"] or "patient"
    token = secrets.token_urlsafe(24)
    with _sessions_lock:
        _sessions[token] = {"patient_id": row["patient_id"], "name": row["name"] or req.username, "role": role}
    return {
        "token": token,
        "patient_id": row["patient_id"],
        "name": row["name"] or req.username,
        "role": role,
    }


# =====================================================================
# 请求/响应模型
# =====================================================================
class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    patient_id: str = "P20240001"  # 未登录时的演示默认（生产应强制登录）
    token: str | None = None


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


def _pending_approval(
    graph_app, thread_id: str, for_patient: bool = False
) -> dict[str, Any] | None:
    """取线程的待审批 payload。for_patient=True 时富化展示字段并剥离内部 ID。"""
    from medical_agent.graphs.hitl import get_pending_interrupt

    intr = get_pending_interrupt(graph_app, _config(thread_id))
    if intr is None:
        return None
    payload = getattr(intr, "value", intr)
    if not isinstance(payload, dict):
        return {"detail": str(payload)}

    if not for_patient:
        return payload

    # 患者视图：带人读字段，剥内部 ID
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DoctorRepository, PatientRepository, ScheduleRepository

    db = get_db()
    prow = PatientRepository(db).get_by_id(payload.get("patient_id", "")) or {}
    doctor = DoctorRepository(db).get_by_id(payload.get("doctor_id") or 0) or {}
    sched = ScheduleRepository(db).get_by_id(payload.get("schedule_id") or 0) or {}
    clean = {
        "type": payload.get("type", ""),
        "action": payload.get("action", ""),
        "patient_name": prow.get("name", ""),
        "schedule_date": payload.get("schedule_date") or sched.get("schedule_date", ""),
        "time_slot": payload.get("time_slot") or sched.get("time_slot", ""),
        "start_time": str(sched.get("start_time", ""))[:5],
        "end_time": str(sched.get("end_time", ""))[:5],
        "department": doctor.get("department", ""),
        "doctor_name": doctor.get("name", ""),
        "doctor_title": doctor.get("title", ""),
        "doctor_line": f"{doctor.get('department', '')} {doctor.get('name', '')} {doctor.get('title', '')}".strip(),
        "symptoms": payload.get("symptoms", ""),
        "duration": payload.get("duration", ""),
        "severity": payload.get("severity", ""),
        "appointment_id": payload.get("appointment_id", ""),
        "reason": payload.get("reason", ""),
        "ask": payload.get("ask", ""),
    }
    return {k: v for k, v in clean.items() if v not in (None, "")}


_TOOL_RESULT_ALLOWED = {
    # 患者可见的业务字段白名单；patient_id/doctor_id/schedule_id/version/error_code 等一律不出站
    "success", "appointment_id", "department", "doctor_name", "doctor_title",
    "schedule_date", "time_slot", "start_time", "end_time", "status",
    "symptoms", "count", "upcoming_count", "history_count", "error_message",
    "cancelled_reason", "is_upcoming", "is_past",
}


def _sanitize_messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """输出侧护栏：
    1. assistant 消息若泄露系统提示词，替换为统一拒绝话术
    2. tool_result 剥离内部字段（LLM 上下文里的原 JSON 不动，只净化出站副本）"""
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
        elif m.get("role") == "tool_result":
            try:
                data = json.loads(m.get("content", "{}"))
            except Exception:
                data = None
            if isinstance(data, dict):
                clean = {k: v for k, v in data.items() if k in _TOOL_RESULT_ALLOWED}
                m = {**m, "content": json.dumps(clean, ensure_ascii=False), "data": clean}
        out.append(m)
    return out


def _pre_checks(text: str, patient_id: str, ip: str) -> dict[str, Any] | None:
    """chat/chat_stream 共用的前置检查：护栏 → 急诊 → 用户级限流。

    返回 None = 放行；否则返回 {"messages": [...], "blocked": bool} 立即响应体。
    """
    # 1) 输入护栏
    from medical_agent.guardrails import check_input

    gr = check_input(text)
    if not gr.is_safe:
        _record_offense(ip)
        return {
            "messages": [
                {"role": "user", "content": text},
                {"role": "assistant", "content": f"🛡️ {gr.reason}", "agent": "guardrail"},
            ],
            "blocked": True,
        }

    # 2) 急诊短路（不调 LLM，立即返回 120 指引）
    from medical_agent.emergency import build_emergency_response, detect_emergency

    is_em, matched = detect_emergency(text)
    if is_em:
        return {
            "messages": [
                {"role": "user", "content": text},
                {"role": "assistant", "content": build_emergency_response(matched), "agent": "emergency"},
            ],
            "blocked": False,
        }

    # 3) 用户级限流
    from medical_agent.rate_limit import check_rate_limit

    allowed, limit_info = check_rate_limit(patient_id)
    if not allowed:
        return {
            "messages": [
                {"role": "user", "content": text},
                {
                    "role": "assistant",
                    "content": f"⏳ 系统繁忙，请 {limit_info.get('retry_after', 60)} 秒后再试。",
                    "agent": "rate_limit",
                },
            ],
            "blocked": True,
        }
    return None


# =====================================================================
# SSE 流式：进度事件映射（白名单话术，不透传内部字段）
# =====================================================================
_NODE_PROGRESS: dict[str, str] = {
    "intake_direct": "📝 正在整理问诊信息…",
    "scheduler_direct": "🗓️ 正在为您匹配时段…",
    "confirmer_direct": "📋 正在核对预约信息…",
    "knowledge_direct": "📚 正在查阅医学知识…",
    "supervisor": "🧭 正在为您分诊…",
}


def _sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_chat(req: ChatRequest, thread_id: str, patient_id: str):
    """SSE 生成器：立即回执 → 路由预告 → progress → messages → pending_approval? → done。"""
    from langchain_core.messages import HumanMessage

    t_start = time.time()
    graph_app = get_graph_app()
    before = _msg_count(graph_app, thread_id)

    # 1) 立即回执（<50ms）——用户立刻知道系统活着
    yield _sse("progress", {"label": "📥 已收到，开始处理…"})

    # 1.5) 该会话有申请正在人工审核中 → 不入图，直接提示等待
    try:
        if _pending_approval(graph_app, thread_id, for_patient=True):
            yield _sse(
                "messages",
                [{"role": "assistant", "content": "您有一项申请正在人工审核中，请等待审核结果后再继续。"}],
            )
            yield _sse("done", {"thread_id": thread_id})
            return
    except Exception:
        pass

    # 2) 路由预告：确定性路由在本地算，0 LLM 成本，直接告诉用户去哪
    last_label = "📥 已收到，开始处理…"
    try:
        from medical_agent.graphs.supervisor import route_after_merge

        snap = graph_app.get_state(_config(thread_id))
        preview_state = {
            **(snap.values or {}),
            "messages": [HumanMessage(content=req.message.strip())],
        }
        route = route_after_merge(preview_state)
        preview_label = _NODE_PROGRESS.get(route)
        if preview_label:
            yield _sse("progress", {"label": preview_label})
            last_label = preview_label
    except Exception:
        pass

    try:
        for mode, chunk in graph_app.stream(
            {"messages": [HumanMessage(content=req.message.strip())], "patient_id": patient_id},
            config=_config(thread_id),
            stream_mode=["updates", "custom"],
        ):
            if mode == "custom" and isinstance(chunk, dict) and chunk.get("type") == "progress":
                lbl = chunk["label"]
                if lbl != last_label:  # 与上一条重复的不发（路由预告可能已发过）
                    yield _sse("progress", {"label": lbl})
                    last_label = lbl
            elif mode == "updates" and isinstance(chunk, dict):
                for node_name in chunk:
                    lbl = _NODE_PROGRESS.get(node_name)
                    if lbl and lbl != last_label:
                        yield _sse("progress", {"label": lbl})
                        last_label = lbl
    except Exception as e:
        print(f"[timing] thread={thread_id} FAILED after {time.time() - t_start:.1f}s: {e}")
        yield _sse("error", {"detail": f"{type(e).__name__}: {e}"})
        return

    print(f"[timing] thread={thread_id} total={time.time() - t_start:.1f}s")
    yield _sse("messages", _sanitize_messages(_new_messages(graph_app, thread_id, before)))
    # 审批只在中台进行：患者端不暴露审批单，仅提示"已提交人工审核"，
    # 结果由前端轮询 /api/threads/{tid}/status 自动送达
    pending = _pending_approval(graph_app, thread_id, for_patient=True)
    if pending:
        yield _sse(
            "submitted",
            {"detail": pending.get("action") or "您的申请已提交人工审核，结果将自动告知"},
        )
    yield _sse("done", {"thread_id": thread_id})


# =====================================================================
# 接口
# =====================================================================
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "medical-appointment-agent"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request) -> Any:
    ip = _client_ip(request)
    for blocked in (_check_ip_allowed(ip), _check_global_allowed()):
        if blocked:
            return blocked

    thread_id = req.thread_id or f"web-{uuid.uuid4().hex[:12]}"
    text = req.message.strip()
    if not text:
        return ChatResponse(thread_id=thread_id, messages=[])

    patient_id, auth_err = _resolve_patient_id(req.token, req.patient_id)
    if auth_err:
        return JSONResponse(status_code=401, content={"detail": auth_err})

    pre = _pre_checks(text, patient_id, ip)
    if pre is not None:
        return ChatResponse(thread_id=thread_id, messages=pre["messages"], blocked=pre["blocked"])

    from langchain_core.messages import HumanMessage

    graph_app = get_graph_app()
    # 有申请正在人工审核 → 不入图
    if _pending_approval(graph_app, thread_id, for_patient=True):
        return ChatResponse(
            thread_id=thread_id,
            messages=[{"role": "assistant", "content": "您有一项申请正在人工审核中，请等待审核结果后再继续。"}],
        )
    before = _msg_count(graph_app, thread_id)
    graph_app.invoke(
        {"messages": [HumanMessage(content=text)], "patient_id": patient_id},
        config=_config(thread_id),
    )

    return ChatResponse(
        thread_id=thread_id,
        messages=_sanitize_messages(_new_messages(graph_app, thread_id, before)),
        pending_approval=None,  # 审批只在中台，不暴露给患者
    )


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest, request: Request) -> Any:
    """SSE 流式对话：进度事件 + 最终消息 + 审批点。"""
    ip = _client_ip(request)
    for blocked in (_check_ip_allowed(ip), _check_global_allowed()):
        if blocked:
            return blocked

    thread_id = req.thread_id or f"web-{uuid.uuid4().hex[:12]}"
    text = req.message.strip()

    patient_id, auth_err = _resolve_patient_id(req.token, req.patient_id)
    if auth_err:
        return JSONResponse(status_code=401, content={"detail": auth_err})

    if not text:
        return StreamingResponse(iter([_sse("done", {"thread_id": thread_id})]), media_type="text/event-stream")

    pre = _pre_checks(text, patient_id, ip)
    if pre is not None:
        def _blocked_stream():
            yield _sse("messages", pre["messages"][1:])  # user 消息前端自己已渲染
            yield _sse("done", {"thread_id": thread_id, "blocked": pre["blocked"]})

        return StreamingResponse(_blocked_stream(), media_type="text/event-stream")

    return StreamingResponse(
        _stream_chat(req, thread_id, patient_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# 说明：患者侧 /api/approve 已移除（v6）——审批单不对患者暴露，
# 核准/驳回统一走中台 /api/admin/approvals/decision（staff 鉴权）。


@app.get("/api/appointments")
def list_appointments(patient_id: str = "P20240001", token: str | None = None) -> Any:
    pid, auth_err = _resolve_patient_id(token, patient_id)
    if auth_err:
        return JSONResponse(status_code=401, content={"detail": auth_err})
    from medical_agent.tools.appointment_query import query_my_appointments

    class _RT:
        state = {"patient_id": pid}

    return json.loads(query_my_appointments.func(runtime=_RT(), limit=20))


# =====================================================================
# 排班可视化（患者直选，v6）
# =====================================================================
class SelectSlotRequest(BaseModel):
    thread_id: str | None = None
    schedule_id: int
    token: str | None = None


@app.get("/api/schedules")
def list_schedules(
    token: str | None = None, department: str | None = None, days: int = 7
) -> Any:
    """未过期排班查询（患者排班面板用）。只含今天起、结束时间未过的时段。"""
    pid, auth_err = _resolve_patient_id(token, "")
    if auth_err or not pid:
        return JSONResponse(status_code=401, content={"detail": auth_err or "请先登录"})

    from datetime import date, timedelta

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DepartmentRepository, ScheduleRepository

    days = max(1, min(days, 14))
    db = get_db()
    today = date.today()
    departments = [d["name"] for d in DepartmentRepository(db).list_all()]
    if department:
        departments = [department] if department in departments else []
    repo = ScheduleRepository(db)
    out: list[dict[str, Any]] = []
    for dept in departments:
        out.extend(
            repo.find_available(
                department=dept, start_date=today, end_date=today + timedelta(days=days - 1)
            )
        )
    out.sort(key=lambda x: (x["schedule_date"], x["start_time"], x["department"], x["doctor_name"]))
    return {"days": days, "count": len(out), "schedules": out}


@app.post("/api/select-slot")
def select_slot_api(req: SelectSlotRequest) -> Any:
    """患者从排班面板直选时段：写入 thread state 的 selected_slot，
    之后患者在对话里发确认消息即可进入既有 confirmer → HITL 审批链路。"""
    pid, auth_err = _resolve_patient_id(req.token, "")
    if auth_err or not pid:
        return JSONResponse(status_code=401, content={"detail": auth_err or "请先登录"})

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DoctorRepository, ScheduleRepository
    from medical_agent.tools.appointment import _recheck_schedule

    recheck = _recheck_schedule(req.schedule_id)
    if not recheck["available"]:
        if recheck["reason"] == "slot_expired":
            detail = "该时段就诊时间已过，请选择其他时段"
        elif recheck["reason"] == "no_remaining":
            detail = "该时段号源已约满，请选择其他时段"
        else:
            detail = f"该时段当前不可约（{recheck['reason']}）"
        return JSONResponse(status_code=409, content={"detail": detail, "reason": recheck["reason"]})

    db = get_db()
    s = ScheduleRepository(db).get_by_id(req.schedule_id)
    doctor = DoctorRepository(db).get_by_id(s["doctor_id"]) or {}
    slot: dict[str, Any] = {
        "schedule_id": s["id"],
        "doctor_id": s["doctor_id"],
        "schedule_version": s["version"],
        "schedule_date": s["schedule_date"],
        "time_slot": s["time_slot"],
        "start_time": s["start_time"],
        "end_time": s["end_time"],
        "doctor_name": doctor.get("name", ""),
        "doctor_title": doctor.get("title", ""),
        "department": doctor.get("department", ""),
    }
    thread_id = req.thread_id or f"web-{uuid.uuid4().hex[:12]}"
    graph_app = get_graph_app()
    # 写进消息历史：确认走确定性节点（confirm_book_direct）从 state 取参，不依赖 LLM；
    # 消息患者端可见，必须保持纯服务话术——不带任何内部指令/字段
    from langchain_core.messages import AIMessage

    slot_desc = (
        f"已为您锁定时段：{slot['schedule_date']} {slot['start_time']}-{slot['end_time']} "
        f"{slot['department']} {slot['doctor_name']}（{slot['doctor_title']}）。"
        f"请发送确认消息完成预约。"
    )
    graph_app.update_state(
        _config(thread_id),
        values={
            "patient_id": pid,
            "selected_slot": slot,
            "current_step": "confirm",
            "messages": [AIMessage(content=slot_desc, name="scheduler_agent")],
        },
    )
    return {
        "success": True,
        "thread_id": thread_id,
        "selected": {
            "date": s["schedule_date"],
            "time": f"{s['start_time']}-{s['end_time']}",
            "department": doctor.get("department", ""),
            "doctor": doctor.get("name", ""),
        },
        "next": "请在对话中发送确认消息（如「确认预约」）以继续",
    }


@app.get("/api/appointments/{appointment_id}")
def appointment_detail(appointment_id: str, patient_id: str = "P20240001", token: str | None = None) -> Any:
    pid, auth_err = _resolve_patient_id(token, patient_id)
    if auth_err:
        return JSONResponse(status_code=401, content={"detail": auth_err})
    from medical_agent.tools.appointment_query import get_appointment_detail

    class _RT:
        state = {"patient_id": pid}

    return json.loads(get_appointment_detail.func(appointment_id=appointment_id, runtime=_RT()))


@app.get("/api/departments")
def departments() -> dict:
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DepartmentRepository

    return {"departments": DepartmentRepository(get_db()).list_all()}


# =====================================================================
# 多模态：病历资料上传（GLM-4V 抽取 + PII 打码，v6）
# =====================================================================
@app.post("/api/upload")
async def upload_document(
    request: Request,
    token: str | None = None,
    thread_id: str | None = None,
    file: UploadFile | None = File(default=None),
) -> Any:
    """上传检查报告/病历照片 → GLM-4V 结构化抽取 → 入库；可选写入对话线程。"""
    pid, auth_err = _resolve_patient_id(token, "")
    if auth_err or not pid:
        return JSONResponse(status_code=401, content={"detail": auth_err or "请先登录"})

    from medical_agent.db.repositories import _APPT_WRITE_LOCK
    from medical_agent.vision import ALLOWED_MIME, MAX_UPLOAD_BYTES, extract_document

    if file is None:
        return JSONResponse(status_code=400, content={"detail": "缺少文件"})
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_MIME:
        return JSONResponse(
            status_code=415,
            content={"detail": "仅支持 jpg/png/webp 图片（PDF 请先截图上传）"},
        )
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"detail": "文件超过 5MB，请压缩后上传"})

    # 落盘（留原始凭证；生产应放对象存储）
    import uuid as _uuid

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(mime, ".bin")
    upload_dir = PROJECT_ROOT / "data" / "uploads" / pid
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{_uuid.uuid4().hex}{ext}"
    (upload_dir / stored_name).write_bytes(data)

    # GLM-4V 抽取（失败不阻塞上传，降级为'待人工识别'）
    try:
        extracted = extract_document(data, mime)
    except Exception as e:
        print(f"[upload] extract failed: {e}")
        extracted = {
            "doc_type": "其他",
            "title": file.filename or "未命名资料",
            "summary": "自动识别失败，已保存原图等待人工查看",
            "symptoms": "",
            "key_fields": [],
            "suggested_department": "",
            "urgent": False,
        }

    from medical_agent.db.database import get_db

    db = get_db()
    with _APPT_WRITE_LOCK:
        cur = db.execute(
            """INSERT INTO patient_documents
               (patient_id, filename, mime_type, size_bytes, doc_type, title, summary, extracted_json, urgent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pid,
                file.filename or stored_name,
                mime,
                len(data),
                extracted.get("doc_type", "其他"),
                extracted.get("title", ""),
                extracted.get("summary", ""),
                json.dumps(extracted, ensure_ascii=False),
                1 if extracted.get("urgent") else 0,
            ),
        )
        db.commit()
        doc_id = cur.lastrowid

    # 写进对话线程（若有）：让问诊抽取能看到资料内容
    if thread_id:
        from langchain_core.messages import AIMessage

        bits = [f"📎 患者上传了{extracted.get('doc_type', '资料')}：《{extracted.get('title') or file.filename}》"]
        if extracted.get("summary"):
            bits.append(f"摘要：{extracted['summary']}")
        if extracted.get("symptoms"):
            bits.append(f"主诉：{extracted['symptoms']}")
        if extracted.get("suggested_department"):
            bits.append(f"建议科室：{extracted['suggested_department']}")
        try:
            get_graph_app().update_state(
                _config(thread_id),
                values={"messages": [AIMessage(content="\n".join(bits), name="document_agent")]},
            )
        except Exception as e:
            print(f"[upload] thread message skipped: {e}")

    return {"success": True, "document_id": doc_id, **extracted}


@app.get("/api/documents")
def list_documents(patient_id: str = "", token: str | None = None) -> Any:
    pid, auth_err = _resolve_patient_id(token, patient_id)
    if auth_err:
        return JSONResponse(status_code=401, content={"detail": auth_err})
    from medical_agent.db.database import get_db

    db = get_db()
    rows = db.execute(
        """SELECT id, doc_type, title, summary, urgent, created_at
           FROM patient_documents WHERE patient_id = ? ORDER BY created_at DESC LIMIT 20""",
        (pid,),
    ).fetchall()
    docs = [
        {
            "id": r["id"],
            "doc_type": r["doc_type"],
            "title": r["title"],
            "summary": r["summary"],
            "urgent": bool(r["urgent"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {"count": len(docs), "documents": docs}


# =====================================================================
# 就诊摘要（v6：聚合历史 + 病历资料 → 辅助摘要，非诊断）
# =====================================================================
_SUMMARY_CACHE: dict[str, tuple[float, str]] = {}
_SUMMARY_TTL = 600.0


@app.get("/api/summary")
def medical_summary(token: str | None = None, refresh: int = 0) -> Any:
    pid, auth_err = _resolve_patient_id(token, "")
    if auth_err or not pid:
        return JSONResponse(status_code=401, content={"detail": auth_err or "请先登录"})

    cached = _SUMMARY_CACHE.get(pid)
    if not refresh and cached and time.time() - cached[0] < _SUMMARY_TTL:
        return {"summary": cached[1], "cached": True}

    from medical_agent.db.database import get_db
    from medical_agent.tools.appointment_query import query_my_appointments

    class _RT:
        state = {"patient_id": pid}

    appts = json.loads(query_my_appointments.func(runtime=_RT(), limit=30))
    db = get_db()
    doc_rows = db.execute(
        """SELECT doc_type, title, summary, created_at FROM patient_documents
           WHERE patient_id = ? ORDER BY created_at DESC LIMIT 20""",
        (pid,),
    ).fetchall()

    hist_lines = [
        f"- {a.get('schedule_date', '')} {a.get('department', '')} {a.get('doctor_name', '')}"
        f"（{a.get('status', '')}）主诉：{a.get('symptoms') or '未记录'}"
        for a in appts.get("appointments", [])
    ]
    doc_lines = [
        f"- {r['created_at'][:10]} {r['doc_type']}《{r['title']}》{r['summary']}"
        for r in doc_rows
    ]
    if not hist_lines and not doc_lines:
        return {
            "summary": "暂无历史预约和病历资料。完成一次预约或上传检查报告后，这里会自动生成就诊摘要。",
            "empty": True,
        }

    from langchain_core.messages import HumanMessage

    from medical_agent.llm import get_llm

    prompt = (
        "你是门诊接诊助手。根据患者的既往就诊记录和病历资料，写一份给接诊医生快速浏览的就诊摘要。\n"
        "要求：① 100 字以内，分条陈述；② 只归纳已有信息，不下诊断、不给治疗建议、不编造；"
        "③ 如有重复出现的症状或异常指标，指出来供医生关注。\n\n"
        "既往就诊：\n" + ("\n".join(hist_lines) or "无") + "\n\n病历资料：\n" + ("\n".join(doc_lines) or "无")
    )
    try:
        resp = get_llm(max_tokens=400).invoke([HumanMessage(content=prompt)])
        text = (resp.content or "").strip() or "摘要生成失败，请稍后重试"
    except Exception as e:
        print(f"[summary] llm failed: {e}")
        text = "摘要生成暂时不可用，请稍后重试。"
    _SUMMARY_CACHE[pid] = (time.time(), text)
    return {"summary": text}


# =====================================================================
# 患者直操：取消 / 改约（v6，预约卡按钮）
# =====================================================================
class PatientCancelRequest(BaseModel):
    reason: str = "个人原因取消"


def _load_owned_appointment(appointment_id: str, pid: str):
    """返回 (appt_dict, error_response)。校验存在性与归属。"""
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import AppointmentRepository

    db = get_db()
    appt = AppointmentRepository(db).get_by_id(appointment_id)
    if appt is None:
        return None, JSONResponse(status_code=404, content={"detail": "预约不存在"})
    if appt["patient_id"] != pid:
        return None, JSONResponse(status_code=403, content={"detail": "无权操作他人预约"})
    return appt, None


@app.post("/api/appointments/{appointment_id}/cancel")
def patient_cancel_appointment(
    appointment_id: str, req: PatientCancelRequest, token: str | None = None
) -> Any:
    """患者主动取消自己的预约（即时生效，审计 actor=patient）。"""
    pid, auth_err = _resolve_patient_id(token, "")
    if auth_err or not pid:
        return JSONResponse(status_code=401, content={"detail": auth_err or "请先登录"})

    appt, err = _load_owned_appointment(appointment_id, pid)
    if err:
        return err
    if appt["status"] not in ("pending", "confirmed"):
        return JSONResponse(
            status_code=409,
            content={"detail": f"当前状态（{appt['status']}）不可取消"},
        )

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import _APPT_WRITE_LOCK, AppointmentRepository

    db = get_db()
    with _APPT_WRITE_LOCK:
        AppointmentRepository(db).update_status(
            appointment_id,
            "cancelled",
            cancelled_reason=req.reason or "患者主动取消",
            actor=f"patient:{pid}",
        )
    return {"success": True, "appointment_id": appointment_id, "status": "cancelled"}


class PatientRescheduleRequest(BaseModel):
    new_schedule_id: int


@app.post("/api/appointments/{appointment_id}/reschedule")
def patient_reschedule_appointment(
    appointment_id: str, req: PatientRescheduleRequest, token: str | None = None
) -> Any:
    """患者改约自己的预约到新时段（乐观锁 + 过期校验 + 审计）。"""
    pid, auth_err = _resolve_patient_id(token, "")
    if auth_err or not pid:
        return JSONResponse(status_code=401, content={"detail": auth_err or "请先登录"})

    appt, err = _load_owned_appointment(appointment_id, pid)
    if err:
        return err
    if appt["status"] != "confirmed":
        return JSONResponse(
            status_code=409,
            content={"detail": f"当前状态（{appt['status']}）不支持改约，仅已确认的预约可改约"},
        )

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import (
        _APPT_WRITE_LOCK,
        AppointmentRepository,
        DoctorRepository,
        ScheduleRepository,
    )
    from medical_agent.tools.appointment import _recheck_schedule

    recheck = _recheck_schedule(req.new_schedule_id)
    if not recheck["available"]:
        detail = (
            "新时段就诊时间已过，请重新选择"
            if recheck["reason"] == "slot_expired"
            else f"新时段当前不可约（{recheck['reason']}）"
        )
        return JSONResponse(status_code=409, content={"detail": detail, "reason": recheck["reason"]})

    db = get_db()
    try:
        with _APPT_WRITE_LOCK:
            AppointmentRepository(db).update_schedule(
                appointment_id=appointment_id,
                new_schedule_id=req.new_schedule_id,
                actor=f"patient:{pid}",
            )
    except Exception as e:  # OptimisticLockError / RepositoryError
        return JSONResponse(status_code=409, content={"detail": f"改约失败：{e}"})

    s = ScheduleRepository(db).get_by_id(req.new_schedule_id) or {}
    doctor = DoctorRepository(db).get_by_id(s.get("doctor_id")) or {}
    return {
        "success": True,
        "appointment_id": appointment_id,
        "schedule": {
            "date": s.get("schedule_date", ""),
            "time": f"{s.get('start_time', '')}-{s.get('end_time', '')}",
            "department": doctor.get("department", ""),
            "doctor": doctor.get("name", ""),
        },
    }


# =====================================================================
# 运行指标（v6：demo 可观测）
# =====================================================================
_STARTED_AT = time.time()


@app.get("/api/metrics")
def metrics() -> dict:
    from medical_agent.global_limiter import get_combined_limiter
    from medical_agent.resilience import get_llm_circuit

    circuit = get_llm_circuit()
    with _security_lock:
        banned_count = sum(1 for until in _blacklist.values() if until > time.time())
    return {
        "uptime_seconds": int(time.time() - _STARTED_AT),
        "active_sessions": len(_sessions),
        "llm_circuit": {
            "state": circuit.state,
            "failure_count": getattr(circuit, "failure_count", None),
            "failure_threshold": getattr(circuit, "failure_threshold", None),
        },
        "rate_limit": {
            "per_ip": _ip_limiter.stats(),
            "global": get_combined_limiter().stats(),
            "banned_ips": banned_count,
        },
        "mock_llm": os.environ.get("MOCK_LLM", "").lower() in ("true", "1", "yes"),
    }


@app.get("/api/security/stats")
def security_stats() -> dict:
    """限流/黑名单运行状态（demo 可观测用）。"""
    from medical_agent.global_limiter import get_combined_limiter

    with _security_lock:
        banned = {ip: int(until - time.time()) for ip, until in _blacklist.items() if until > time.time()}
    return {
        "ip_limiter": _ip_limiter.stats(),
        "global": get_combined_limiter().stats(),
        "banned_ips": banned,
    }


# =====================================================================
# 业务中台（staff 视角，v6）：审批队列 + 排班/预约管理 + 审计
# =====================================================================
def _guard_staff(request: Request, token: str | None) -> JSONResponse | None:
    if _staff_session(token, request) is None:
        return JSONResponse(status_code=403, content={"detail": "需要业务中台权限（staff 账号或 X-Admin-Token）"})
    return None


@app.get("/api/admin/approvals")
def admin_approvals(request: Request, token: str | None = None) -> Any:
    """全局待审批队列：扫描 checkpointer 里的活跃线程，收集停在人工审批点的申请。"""
    guard = _guard_staff(request, token)
    if guard:
        return guard
    items = _scan_pending_approvals()
    return {"count": len(items), "approvals": items}


def _scan_pending_approvals(limit: int = 200) -> list[dict[str, Any]]:
    """扫描所有线程的人工审批点（REST 与 SSE 流共用）。"""
    graph_app = get_graph_app()
    from medical_agent.db.database import get_db

    db = get_db()
    items, seen = [], set()
    try:
        checkpoint_iter = graph_app.checkpointer.list(None, limit=limit)
    except Exception:
        checkpoint_iter = []
    for tup in checkpoint_iter:
        try:
            tid = tup.config["configurable"]["thread_id"]
        except Exception:
            continue
        if tid in seen:
            continue
        seen.add(tid)
        try:
            snap = graph_app.get_state(_config(tid))
        except Exception:
            continue
        for task in getattr(snap, "tasks", []) or []:
            intrs = getattr(task, "interrupts", None) or []
            if not intrs:
                continue
            payload = getattr(intrs[0], "value", None)
            if not isinstance(payload, dict):
                continue
            pid = payload.get("patient_id", "")
            prow = db.execute("SELECT name, phone FROM patients WHERE id = ?", (pid,)).fetchone()
            items.append(
                {
                    "thread_id": tid,
                    "type": payload.get("type", ""),
                    "action": payload.get("action", ""),
                    "patient_id": pid,
                    "patient_name": (prow["name"] if prow else "") or pid,
                    "patient_phone": (prow["phone"] if prow else "") or "",
                    "schedule_date": payload.get("schedule_date", ""),
                    "time_slot": payload.get("time_slot", ""),
                    "doctor_id": payload.get("doctor_id"),
                    "symptoms": payload.get("symptoms", ""),
                    "duration": payload.get("duration", ""),
                    "severity": payload.get("severity", ""),
                    "ask": payload.get("ask", ""),
                }
            )
            break
    return items


@app.get("/api/admin/approvals/stream")
def admin_approvals_stream(request: Request, token: str | None = None) -> Any:
    """SSE：中台审批队列实时流。队列指纹变化时推全量快照，无变化时发心跳。"""
    guard = _guard_staff(request, token)
    if guard:
        return guard

    def _gen():
        last_fp = None
        polls = 0
        while True:
            try:
                items = _scan_pending_approvals()
                fp = json.dumps([(i["thread_id"], i["type"]) for i in items], ensure_ascii=False)
                if fp != last_fp:
                    last_fp = fp
                    yield _sse("approvals", {"count": len(items), "approvals": items})
            except Exception as e:
                yield _sse("error", {"detail": f"scan failed: {e}"})
                return
            polls += 1
            if polls % 8 == 0:
                yield ": ping\n\n"  # 保活，防代理断连
            time.sleep(2.5)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class AdminDecisionRequest(BaseModel):
    thread_id: str
    decision: str  # "approve" | "reject:原因"


@app.get("/api/threads/{thread_id}/status")
def thread_status(thread_id: str, token: str | None = None, since: int = 0) -> Any:
    """患者轮询自己线程的状态：新消息 + 是否仍有待审批。

    中台处理后患者端据此自动更新（审批结果消息随线程返回）。"""
    pid, auth_err = _resolve_patient_id(token, "")
    if auth_err or not pid:
        return JSONResponse(status_code=401, content={"detail": auth_err or "请先登录"})

    graph_app = get_graph_app()
    try:
        snap = graph_app.get_state(_config(thread_id))
    except Exception:
        return JSONResponse(status_code=404, content={"detail": "会话不存在"})

    values = snap.values or {}
    # 会话归属校验：只能看自己的线程
    if values.get("patient_id") and values["patient_id"] != pid:
        return JSONResponse(status_code=403, content={"detail": "无权查看该会话"})

    msgs = _sanitize_messages(_new_messages(graph_app, thread_id, max(0, since)))
    pending = _pending_approval(graph_app, thread_id, for_patient=True)
    return {
        "thread_id": thread_id,
        "msg_count": len(values.get("messages", [])),
        "messages": msgs,
        "pending_approval": pending,
    }


@app.post("/api/admin/approvals/decision")
def admin_decide(req: AdminDecisionRequest, request: Request, token: str | None = None) -> Any:
    """中台处理申请：通过 / 驳回（带原因）。resume 线程内 interrupt，落库并返回结果。"""
    guard = _guard_staff(request, token)
    if guard:
        return guard

    from medical_agent.graphs.hitl import resume_with_decision

    graph_app = get_graph_app()
    before = _msg_count(graph_app, req.thread_id)
    resume_with_decision(graph_app, _config(req.thread_id), req.decision)
    return {
        "success": True,
        "thread_id": req.thread_id,
        "messages": _sanitize_messages(_new_messages(graph_app, req.thread_id, before)),
        "pending_approval": _pending_approval(graph_app, req.thread_id, for_patient=True),
    }


@app.get("/api/admin/stats")
def admin_stats(request: Request, token: str | None = None) -> Any:
    guard = _guard_staff(request, token)
    if guard:
        return guard
    from medical_agent.admin_tools import admin_stats_today

    return admin_stats_today()


@app.get("/api/admin/schedules/view")
def admin_schedules_view(
    request: Request, token: str | None = None, days: int = 7, department: str | None = None
) -> Any:
    """排班总览（中台可视化用）：含满员号源（remaining=0），只看今天起的前 N 天。"""
    guard = _guard_staff(request, token)
    if guard:
        return guard

    from datetime import date, timedelta

    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DepartmentRepository, ScheduleRepository

    days = max(1, min(days, 14))
    db = get_db()
    today = date.today()
    departments = [d["name"] for d in DepartmentRepository(db).list_all()]
    if department:
        departments = [department] if department in departments else []
    repo = ScheduleRepository(db)
    out: list[dict[str, Any]] = []
    for dept in departments:
        out.extend(
            repo.find_available(
                department=dept,
                start_date=today,
                end_date=today + timedelta(days=days - 1),
                min_remaining=0,
                include_past=True,
            )
        )
    out.sort(key=lambda x: (x["schedule_date"], x["start_time"], x["department"], x["doctor_name"]))
    return {"days": days, "count": len(out), "schedules": out}


@app.get("/api/admin/appointments/search")
def admin_appointments_search(
    request: Request,
    token: str | None = None,
    q: str = "",
    status: str = "",
    limit: int = 100,
) -> Any:
    """预约检索（中台用）：关键词匹配 预约号/患者/医生/科室/症状/日期，可按状态过滤。"""
    guard = _guard_staff(request, token)
    if guard:
        return guard

    from medical_agent.db.database import get_db

    db = get_db()
    sql = """
        SELECT a.id, a.status, a.symptoms, a.severity, a.created_at, a.cancelled_reason,
               p.name  AS patient_name,
               d.name  AS doctor_name, d.department,
               s.schedule_date, s.time_slot, s.start_time, s.end_time
        FROM appointments a
        LEFT JOIN patients p ON p.id = a.patient_id
        JOIN doctors d ON d.id = a.doctor_id
        JOIN schedules s ON s.id = a.schedule_id
        WHERE 1=1
    """
    params: list[Any] = []
    if q.strip():
        like = f"%{q.strip()}%"
        sql += """ AND (a.id LIKE ? OR a.symptoms LIKE ? OR p.name LIKE ?
                   OR d.name LIKE ? OR d.department LIKE ? OR s.schedule_date LIKE ?)"""
        params.extend([like] * 6)
    if status.strip():
        sql += " AND a.status = ?"
        params.append(status.strip())
    sql += " ORDER BY a.created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 300)))
    rows = db.execute(sql, params).fetchall()
    items = [dict(r) for r in rows]
    return {"count": len(items), "appointments": items}


@app.get("/api/admin/doctors")
def admin_list_doctors(request: Request, token: str | None = None) -> Any:
    guard = _guard_staff(request, token)
    if guard:
        return guard
    from medical_agent.db.database import get_db
    from medical_agent.db.repositories import DoctorRepository

    return {"doctors": DoctorRepository(get_db()).list_all()}


@app.get("/api/admin/audit")
def admin_audit(request: Request, limit: int = 30, token: str | None = None) -> Any:
    guard = _guard_staff(request, token)
    if guard:
        return guard
    from medical_agent.admin_tools import admin_recent_audit_log

    return {"audit": admin_recent_audit_log(limit=max(1, min(limit, 200)))}


class AdminScheduleRequest(BaseModel):
    doctor_id: int
    schedule_date: str  # YYYY-MM-DD
    time_slot: str  # morning/afternoon/evening
    capacity: int = 20


@app.post("/api/admin/schedules")
def admin_create_schedule_route(req: AdminScheduleRequest, request: Request, token: str | None = None) -> Any:
    guard = _guard_staff(request, token)
    if guard:
        return guard
    from medical_agent.admin_tools import admin_create_schedule

    return admin_create_schedule(
        doctor_id=req.doctor_id,
        schedule_date=req.schedule_date,
        time_slot=req.time_slot,
        capacity=req.capacity,
    )


class AdminScheduleOpRequest(BaseModel):
    reason: str = ""
    new_capacity: int = 0


@app.post("/api/admin/schedules/{schedule_id}/{op}")
def admin_schedule_op(schedule_id: int, op: str, req: AdminScheduleOpRequest, request: Request, token: str | None = None) -> Any:
    """op ∈ cancel / restore / capacity。"""
    guard = _guard_staff(request, token)
    if guard:
        return guard
    from medical_agent.admin_tools import (
        admin_adjust_capacity,
        admin_cancel_schedule,
        admin_restore_schedule,
    )

    if op == "cancel":
        return admin_cancel_schedule(schedule_id, reason=req.reason or "中台停用")
    if op == "restore":
        return admin_restore_schedule(schedule_id)
    if op == "capacity":
        if req.new_capacity <= 0:
            return {"success": False, "error_message": "new_capacity 必须 > 0"}
        return admin_adjust_capacity(schedule_id, new_capacity=req.new_capacity)
    return JSONResponse(status_code=404, content={"detail": f"未知操作 {op}"})


class AdminDoctorRequest(BaseModel):
    name: str
    department: str
    title: str = "主治医师"
    specialty: str = ""


@app.post("/api/admin/doctors")
def admin_create_doctor_route(req: AdminDoctorRequest, request: Request, token: str | None = None) -> Any:
    guard = _guard_staff(request, token)
    if guard:
        return guard
    from medical_agent.admin_tools import admin_create_doctor

    return admin_create_doctor(name=req.name, department=req.department, title=req.title, specialty=req.specialty)


class AdminCancelApptRequest(BaseModel):
    reason: str = ""


@app.post("/api/admin/appointments/{appointment_id}/cancel")
def admin_cancel_appointment_route(appointment_id: str, req: AdminCancelApptRequest, request: Request, token: str | None = None) -> Any:
    guard = _guard_staff(request, token)
    if guard:
        return guard
    from medical_agent.admin_tools import admin_cancel_appointment

    return admin_cancel_appointment(appointment_id, reason=req.reason or "中台取消")


@app.post("/api/security/unban")
def security_unban(request: Request) -> Any:
    """解封 IP（压测/运维用）。需 X-Admin-Token 匹配服务端环境变量 MEDICAL_ADMIN_TOKEN。"""
    import os

    admin_token = os.environ.get("MEDICAL_ADMIN_TOKEN", "")
    if not admin_token:
        return JSONResponse(status_code=404, content={"detail": "not found"})
    if request.headers.get("X-Admin-Token") != admin_token:
        return JSONResponse(status_code=403, content={"detail": "无效的管理令牌"})

    ip = _client_ip(request)
    with _security_lock:
        _blacklist.pop(ip, None)
        _offenses.pop(ip, None)
    _ip_limiter.reset_user(ip)
    return {"unbanned": ip}


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
