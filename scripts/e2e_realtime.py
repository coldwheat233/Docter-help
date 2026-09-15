"""E2E 验证方案 B 双端实时性：
1. staff 挂上 SSE 流
2. 患者（另一连接）提交预约 → SSE 流应在几秒内推出新申请
3. 中台（模拟另一会话）批准 → 患者轮询端点应看到 pending 消失 + 结果消息
"""
import json
import threading
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, token=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    url = path
    if token:
        url = f"{path}{'&' if '?' in path else '?'}token={token}"
    req = urllib.request.Request(BASE + url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat_stream(message, thread_id, token):
    body = json.dumps({"message": message, "thread_id": thread_id, "token": token}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/chat/stream", data=body,
                                 headers={"Content-Type": "application/json"})
    events = []
    ev, buf = None, ""
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line == "":
                if ev and buf:
                    events.append((ev, json.loads(buf)))
                ev, buf = None, ""
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                buf = line[5:].strip()
    if ev and buf:
        events.append((ev, json.loads(buf)))
    return events


def main():
    # 登录
    staff = call("POST", "/api/login", {"username": "staff", "password": "Staff123456"})
    patient = call("POST", "/api/login", {"username": "glmtest02", "password": "Test123456!"})
    stok, ptok = staff["token"], patient["token"]

    # 1. staff 挂 SSE 流（后台线程收集事件）
    sse_events = []

    def consume_sse():
        req = urllib.request.Request(
            BASE + f"/api/admin/approvals/stream?token={stok}")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                ev, buf = None, ""
                for raw in resp:
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if line == "":
                        if ev and buf:
                            sse_events.append((time.time(), ev, json.loads(buf)))
                        ev, buf = None, ""
                        continue
                    if line.startswith("event:"):
                        ev = line[6:].strip()
                    elif line.startswith("data:"):
                        buf = line[5:].strip()
        except Exception:
            pass

    t = threading.Thread(target=consume_sse, daemon=True)
    t.start()
    time.sleep(2)  # 等 SSE 连上

    # 2. 患者提交预约
    s = call("GET", f"/api/schedules?token={ptok}&days=7")
    target = sorted(s["schedules"], key=lambda x: (x["schedule_date"], x["start_time"]))[0]
    r3 = call("POST", "/api/select-slot", {"schedule_id": target["schedule_id"], "token": ptok})
    tid = r3["thread_id"]
    submit_time = time.time()
    for ev, data in chat_stream("好的，确认预约", tid, ptok):
        if ev == "pending_approval":
            break
    print(f"患者已提交（{target['schedule_date']} {target['doctor_name']}）")

    # 3. 等待 SSE 推送新申请
    pushed_at = None
    deadline = time.time() + 20
    while time.time() < deadline and pushed_at is None:
        for ts, ev, data in sse_events:
            if ev == "approvals" and any(a["thread_id"] == tid for a in data["approvals"]):
                pushed_at = ts
                break
        time.sleep(0.5)
    if pushed_at:
        print(f"SSE 推送新申请 ✓ 延迟 {pushed_at - submit_time:.1f}s（含患者流结束时间）")
    else:
        print("SSE 未在 20s 内推送新申请 ✗")

    # 4. 患者端轮询状态（模拟 App.tsx 的 3s 轮询）
    poll = call("GET", f"/api/threads/{tid}/status?token={ptok}")
    assert poll["pending_approval"], "患者侧应看到待审批"
    print("患者轮询：待审批中 ✓")

    # 5. 中台核准
    d = call("POST", f"/api/admin/approvals/decision?token={stok}",
             {"thread_id": tid, "decision": "approve"})
    assert d["success"]
    approve_time = time.time()
    print("中台已核准")

    # 6. 患者轮询应看到 pending 消失 + 结果消息
    result_at = None
    deadline = time.time() + 20
    while time.time() < deadline and result_at is None:
        poll = call("GET", f"/api/threads/{tid}/status?token={ptok}")
        if not poll["pending_approval"]:
            result_at = time.time()
            last = [m for m in poll["messages"] if m.get("role") == "assistant"]
            print("结果消息:", last[-1]["content"][:70] if last else poll["messages"][-1])
            break
        time.sleep(1)
    if result_at:
        print(f"患者端感知审批结果 ✓ 延迟 {result_at - approve_time:.1f}s")
    else:
        print("患者端未在 20s 内感知到结果 ✗")

    ok = pushed_at and result_at
    print("PASSED ✓" if ok else "FAILED ✗")


if __name__ == "__main__":
    main()
