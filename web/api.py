"""FastAPI 后端：React 前端的 API 层（v5）。

保留原有 LangGraph 链路不动，这里只做 HTTP 包装：
- 启动预热：lifespan 里编译图 + 预载 embedding（首问不再冷启动）
- SSE 流式：/api/chat/stream 推送进度事件（白名单话术，不透传内部字段）
- 护栏 / 急诊短路 / 三层限流（IP + 用户 + 全局令牌桶 + 攻击黑名单）
- 用户体系：register/login 发 token，patient_id 来自登录态而非客户端自报
- HITL：chat 返回 pending_approval → 前端渲染审批卡 → POST /api/approve resume

启动：
    python web/api.py
    # 或 uvicorn web.api:app --port 8000 --reload

接口：
- POST /api/register     {username, password, name, phone?}
- POST /api/login        {username, password} → {token, patient_id, name}
- POST /api/chat         {message, thread_id?, token? | patient_id}
- POST /api/chat/stream  同上，SSE 流式（progress / messages / pending_approval / done）
- POST /api/approve      {thread_id, decision}          decision: "approve" | "reject:原因"
- GET  /api/appointments?patient_id= 或 ?token=
- GET  /api/appointments/{appointment_id}
- GET  /api/departments
- GET  /api/health
- GET  /api/security/stats  限流/黑名单状态
"""

from __future__ import annotations

import hashlib
import json
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

from fastapi import FastAPI, Request
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
    """token → patient_id。返回 (patient_id, error)。"""
    if token:
        with _sessions_lock:
            pid = _sessions.get(token)
        if pid:
            return pid, None
        return fallback, "token 无效或已过期，请重新登录"
    return fallback, None


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
        _sessions[token] = patient_id
    return {"token": token, "patient_id": patient_id, "name": req.name}


@app.post("/api/login")
def login(req: LoginRequest, request: Request) -> Any:
    blocked = _check_ip_allowed(_client_ip(request))
    if blocked:
        return blocked
    from medical_agent.db.database import get_db

    db = get_db()
    row = db.execute(
        """SELECT u.password_hash, u.salt, u.patient_id, p.name
           FROM users u LEFT JOIN patients p ON p.id = u.patient_id
           WHERE u.username = ?""",
        (req.username,),
    ).fetchone()
    if not row or row["password_hash"] != _hash_password(req.password, row["salt"]):
        return JSONResponse(status_code=401, content={"detail": "用户名或密码错误"})

    token = secrets.token_urlsafe(24)
    with _sessions_lock:
        _sessions[token] = row["patient_id"]
    return {"token": token, "patient_id": row["patient_id"], "name": row["name"] or req.username}


# =====================================================================
# 请求/响应模型
# =====================================================================
class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    patient_id: str = "P20240001"  # 未登录时的演示默认（生产应强制登录）
    token: str | None = None


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
    pending = _pending_approval(graph_app, thread_id)
    if pending:
        yield _sse("pending_approval", pending)
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
    before = _msg_count(graph_app, thread_id)
    graph_app.invoke(
        {"messages": [HumanMessage(content=text)], "patient_id": patient_id},
        config=_config(thread_id),
    )

    return ChatResponse(
        thread_id=thread_id,
        messages=_sanitize_messages(_new_messages(graph_app, thread_id, before)),
        pending_approval=_pending_approval(graph_app, thread_id),
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


@app.post("/api/approve", response_model=ChatResponse)
def approve(req: ApproveRequest, request: Request) -> Any:
    ip = _client_ip(request)
    for blocked in (_check_ip_allowed(ip), _check_global_allowed()):
        if blocked:
            return blocked

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
def list_appointments(patient_id: str = "P20240001", token: str | None = None) -> Any:
    pid, auth_err = _resolve_patient_id(token, patient_id)
    if auth_err:
        return JSONResponse(status_code=401, content={"detail": auth_err})
    from medical_agent.tools.appointment_query import query_my_appointments

    class _RT:
        state = {"patient_id": pid}

    return json.loads(query_my_appointments.func(runtime=_RT(), limit=20))


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
