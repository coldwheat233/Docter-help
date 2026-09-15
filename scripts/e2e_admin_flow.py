"""E2E 验证业务中台：患者提交申请 → staff 队列可见 → 核准/驳回 → 落库。"""
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, token=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    url = path
    if token:
        url = f"{path}{'&' if '?' in path else '?'}token={token}"
    req = urllib.request.Request(BASE + url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def chat_stream(message, thread_id, token):
    body = json.dumps({"message": message, "thread_id": thread_id, "token": token}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/chat/stream", data=body,
                                 headers={"Content-Type": "application/json"})
    events, t0 = [], time.time()
    ev, buf = None, ""
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line == "":
                if ev and buf:
                    events.append((ev, json.loads(buf), time.time() - t0))
                ev, buf = None, ""
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                buf = line[5:].strip()
    if ev and buf:
        events.append((ev, json.loads(buf), time.time() - t0))
    return events


def main():
    # 患者登录 + 选号 + 确认（产生待审批申请）
    _, r = call("POST", "/api/login", {"username": "glmtest02", "password": "Test123456!"})
    ptok = r["token"]
    _, s = call("GET", f"/api/schedules?token={ptok}&days=7")
    target = sorted(s["schedules"], key=lambda x: (x["schedule_date"], x["start_time"]))[0]
    print("患者选号:", target["schedule_id"], target["schedule_date"], target["doctor_name"], target["department"])
    _, r3 = call("POST", "/api/select-slot", {"schedule_id": target["schedule_id"], "token": ptok})
    tid = r3["thread_id"]
    pending = None
    for ev, data, dt in chat_stream("好的，确认预约", tid, ptok):
        if ev == "pending_approval":
            pending = data
    assert pending, "患者侧未产生待审批申请"
    print("患者已提交申请，等中台审批（thread:", tid, "）")

    # 患者权限隔离：患者 token 不能访问中台
    st, _ = call("GET", f"/api/admin/approvals?token={ptok}")
    print("患者访问中台队列 →", st)
    assert st == 403, "患者居然能访问中台！"

    # staff 登录
    _, sr = call("POST", "/api/login", {"username": "staff", "password": "Staff123456"})
    assert sr.get("role") == "staff", sr
    stok = sr["token"]
    print("staff 登录 ok, role:", sr["role"])

    st, q = call("GET", f"/api/admin/approvals?token={stok}")
    assert st == 200
    print(f"中台队列: {q['count']} 条待审批")
    mine = [a for a in q["approvals"] if a["thread_id"] == tid]
    assert mine, "队列里没找到刚提交的申请！"
    print("队列命中刚提交的申请:", json.dumps(mine[0], ensure_ascii=False)[:160])

    # staff 核准 → 落库
    st, d = call("POST", f"/api/admin/approvals/decision?token={stok}",
                 {"thread_id": tid, "decision": "approve"})
    assert st == 200 and d.get("success"), d
    last = [m for m in d["messages"] if m.get("role") == "assistant"]
    print("核准结果:", last[-1]["content"][:90] if last else d)

    # 队列清空该条
    st, q2 = call("GET", f"/api/admin/approvals?token={stok}")
    still = [a for a in q2["approvals"] if a["thread_id"] == tid]
    print("处理后队列中该条:", "仍在（异常）" if still else "已消失 ✓")

    # 驳回路径：用 diag 遗留的待审批线程（如果有）
    others = [a for a in q2["approvals"] if a["type"] == "appointment_create"]
    if others:
        victim = others[0]
        st, d2 = call("POST", f"/api/admin/approvals/decision?token={stok}",
                      {"thread_id": victim["thread_id"], "decision": "reject:时段号源紧张，请改约其他时间"})
        print("驳回遗留申请:", st, "ok" if st == 200 else d2)

    # stats + audit
    st, stats = call("GET", f"/api/admin/stats?token={stok}")
    print("今日概览:", stats)
    st, audit = call("GET", f"/api/admin/audit?token={stok}&limit=5")
    print("审计条数:", len(audit.get("audit", [])))
    print("PASSED ✓")


if __name__ == "__main__":
    main()
