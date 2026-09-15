"""E2E 验证排班直选 → 确定性落库 → HITL 审批全链路（正确的 SSE 解析）。"""
import json
import time
import urllib.error
import urllib.request
from urllib.parse import quote

BASE = "http://127.0.0.1:8000"


def call(method, path, body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def chat_stream(message, thread_id, token):
    """正确的 SSE 解析：event: 行 + data: 行成对出现。"""
    body = json.dumps({"message": message, "thread_id": thread_id, "token": token}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/chat/stream", data=body,
                                 headers={"Content-Type": "application/json"})
    events, t0 = [], time.time()
    ev, buf = None, ""
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n").rstrip("\r")
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
    _, r = call("POST", "/api/login", {"username": "glmtest02", "password": "Test123456!"})
    token = r["token"]
    print("login ok:", r["patient_id"])

    st, s = call("GET", f"/api/schedules?token={token}&days=7")
    from collections import Counter
    c = Counter(x["department"] for x in s["schedules"])
    dept = c.most_common(1)[0][0]
    target = sorted([x for x in s["schedules"] if x["department"] == dept],
                    key=lambda x: (x["schedule_date"], x["start_time"]))[0]
    print("目标时段:", target["schedule_id"], target["schedule_date"],
          target["start_time"], target["doctor_name"], dept)

    st, r3 = call("POST", "/api/select-slot", {"schedule_id": target["schedule_id"], "token": token})
    assert st == 200, r3
    tid = r3["thread_id"]
    print("select-slot ok:", r3["selected"], "thread:", tid)

    pending = None
    for ev, data, dt in chat_stream("好的，确认预约", tid, token):
        if ev == "progress":
            print(f"  [{dt:5.1f}s] progress: {data.get('label')}")
        elif ev == "messages":
            for m in data:
                print(f"  [{dt:5.1f}s] msg: {m.get('role')}/{m.get('agent') or ''} {str(m.get('content'))[:80]}")
        elif ev == "pending_approval":
            pending = data
            print(f"  [{dt:5.1f}s] PENDING: {json.dumps(data, ensure_ascii=False)[:140]}")
        elif ev == "error":
            print(f"  [{dt:5.1f}s] ERROR: {data}")
        elif ev == "done":
            print(f"  [{dt:5.1f}s] DONE")
    assert pending, "未收到 pending_approval！"
    print("=> HITL 审批卡已出现\n")

    st, r5 = call("POST", "/api/approve", {"thread_id": tid, "decision": "approve"})
    last = [m for m in r5["messages"] if m.get("role") == "assistant"]
    print("审批后回复:", last[-1]["content"][:100] if last else r5)

    st, r6 = call("GET", f"/api/appointments?token={token}")
    up = [a for a in r6["appointments"] if a.get("is_upcoming")]
    print("即将就诊:", [(a["appointment_id"], a["schedule_date"], a["department"], a["doctor_name"]) for a in up])
    print("PASSED ✓")


if __name__ == "__main__":
    main()
