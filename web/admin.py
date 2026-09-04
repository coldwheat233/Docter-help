"""Web 业务中台（Admin Panel）。

URL: http://localhost:8501/?admin=1
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import streamlit as st

from medical_agent.admin_tools import (
    admin_adjust_capacity,
    admin_cancel_appointment,
    admin_cancel_schedule,
    admin_create_doctor,
    admin_create_schedule,
    admin_recent_audit_log,
    admin_restore_schedule,
    admin_stats_today,
)
from medical_agent.db.database import get_db
from medical_agent.db.repositories import (
    AppointmentRepository,
    DepartmentRepository,
    DoctorRepository,
    ScheduleRepository,
)


st.set_page_config(page_title="业务中台 · Medical Agent", page_icon="⚙️", layout="wide")
st.title("⚙️ 业务中台（Admin）")
st.caption("供医院管理员使用 · 所有操作会写入审计日志")

# ============================
# 侧边栏
# ============================
with st.sidebar:
    st.header("📊 今日统计")
    stats = admin_stats_today()
    st.metric("总预约", stats["total_appointments"])
    st.metric("已确认", stats["confirmed"])
    st.metric("已取消", stats["cancelled"])
    st.metric("已完成", stats["completed"])
    st.divider()
    st.metric("排班", stats["total_schedules"])
    st.metric("医生", stats["total_doctors"])
    st.metric("患者", stats["total_patients"])
    st.divider()
    st.caption("操作员：admin")
    if st.button("🔄 刷新", use_container_width=True):
        st.rerun()

# ============================
# Tab 切换
# ============================
tab_sched, tab_appt, tab_doc, tab_audit = st.tabs(
    ["📅 排班管理", "📋 预约管理", "👨‍⚕️ 医生管理", "📜 审计日志"]
)

db = get_db()

# =====================================================================
# Tab 1: 排班管理
# =====================================================================
with tab_sched:
    st.subheader("排班列表")
    sched_repo = ScheduleRepository(db)
    doc_repo = DoctorRepository(db)
    dept_repo = DepartmentRepository(db)

    col1, col2, col3 = st.columns(3)
    with col1:
        filter_date = st.date_input("日期（可选）", value=None)
    with col2:
        filter_dept = st.selectbox(
            "科室（可选）",
            options=["全部"] + [d["name"] for d in dept_repo.list_all()],
        )
    with col3:
        filter_status = st.selectbox(
            "状态", options=["全部", "可约", "已停"]
        )

    # 加载排班
    doctors = {d["id"]: d for d in doc_repo.list_all()}
    schedules = sched_repo.find_available.__wrapped__ if False else None  # 用 list_all 不行（无此方法）
    # 直接查
    sql = "SELECT s.*, d.name as doctor_name, d.department FROM schedules s JOIN doctors d ON d.id = s.doctor_id"
    conditions = []
    params = []
    if filter_date:
        conditions.append("s.schedule_date = ?")
        params.append(filter_date.isoformat())
    if filter_dept and filter_dept != "全部":
        conditions.append("d.department = ?")
        params.append(filter_dept)
    if filter_status == "可约":
        conditions.append("s.is_available = 1")
    elif filter_status == "已停":
        conditions.append("s.is_available = 0")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY s.schedule_date DESC, s.time_slot LIMIT 50"
    rows = db.execute(sql, params).fetchall()

    st.write(f"找到 {len(rows)} 条")
    for r in rows:
        r = dict(r)
        col1, col2, col3, col4, col5, col6, col7 = st.columns([2, 2, 1.5, 1, 1, 1, 1.5])
        with col1:
            st.write(f"**{r['doctor_name']}**")
        with col2:
            st.write(f"{r['department']} · {r['time_slot']}")
        with col3:
            st.write(f"📅 {r['schedule_date']}")
        with col4:
            st.write(f"剩 {r['remaining']}/{r['capacity']}")
        with col5:
            if r["is_available"]:
                st.success("可约")
            else:
                st.error("停诊")
        with col6:
            v = r["version"]
            st.caption(f"v{v}")
        with col7:
            if r["is_available"]:
                if st.button("停诊", key=f"cancel_{r['id']}"):
                    res = admin_cancel_schedule(r["id"], reason="管理员停诊")
                    if res["success"]:
                        st.success("已停诊")
                        st.rerun()
            else:
                if st.button("恢复", key=f"restore_{r['id']}"):
                    res = admin_restore_schedule(r["id"])
                    if res["success"]:
                        st.success("已恢复")
                        st.rerun()
        with st.expander(f"加号/减号 #{r['id']}"):
            new_cap = st.number_input(
                "新容量", min_value=int(r["remaining"]), max_value=200, value=int(r["capacity"]), key=f"cap_{r['id']}"
            )
            if st.button("调整", key=f"adj_{r['id']}"):
                res = admin_adjust_capacity(r["id"], int(new_cap))
                if res["success"]:
                    st.success(f"已调整 {res['old_capacity']} → {res['new_capacity']}")
                    st.rerun()
                else:
                    st.error(res["error_message"])

    st.divider()
    st.subheader("新建排班")
    with st.form("new_schedule"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            doctors_list = [(d["id"], f"{d['name']}（{d['department']}）") for d in doctors.values()]
            new_doc = st.selectbox(
                "医生",
                options=[d[0] for d in doctors_list],
                format_func=lambda x: next(d[1] for d in doctors_list if d[0] == x),
            )
        with c2:
            new_date = st.date_input("日期", value=date.today() + timedelta(days=1))
        with c3:
            new_slot = st.selectbox("时段", options=["morning", "afternoon", "evening"])
        with c4:
            new_cap = st.number_input("容量", min_value=1, max_value=200, value=20)
        if st.form_submit_button("创建"):
            res = admin_create_schedule(
                doctor_id=int(new_doc),
                schedule_date=new_date.isoformat(),
                time_slot=new_slot,
                capacity=int(new_cap),
            )
            if res["success"]:
                st.success(f"✅ 已创建 schedule_id={res['schedule_id']}")
                st.rerun()
            else:
                st.error(res["error_message"])

# =====================================================================
# Tab 2: 预约管理
# =====================================================================
with tab_appt:
    st.subheader("预约列表")
    appt_repo = AppointmentRepository(db)
    col1, col2, col3 = st.columns(3)
    with col1:
        appt_status = st.selectbox(
            "状态", options=["全部", "confirmed", "cancelled", "completed", "pending"]
        )
    with col2:
        appt_limit = st.number_input("条数", min_value=10, max_value=500, value=50)
    with col3:
        st.write("")

    appts = appt_repo.list_by_patient(  # 复用 list_by_patient
        patient_id="",  # 实际全查
        status=appt_status if appt_status != "全部" else None,
    ) if False else []

    # 查全部（用 SQL）
    sql = "SELECT * FROM appointments"
    if appt_status != "全部":
        sql += f" WHERE status = '{appt_status}'"
    sql += f" ORDER BY created_at DESC LIMIT {int(appt_limit)}"
    appts = [dict(r) for r in db.execute(sql).fetchall()]

    st.write(f"找到 {len(appts)} 条")
    for a in appts:
        col1, col2, col3, col4, col5 = st.columns([2, 1.5, 1.5, 1, 1])
        with col1:
            st.write(f"**{a['id']}**")
            st.caption(f"患者 {a['patient_id']} · {a.get('symptoms', '')[:30]}")
        with col2:
            st.write(f"医生 {a['doctor_id']} · 排班 {a['schedule_id']}")
        with col3:
            st.write(a.get("created_at", ""))
        with col4:
            status_emoji = {
                "confirmed": "✅",
                "pending": "⏳",
                "cancelled": "❌",
                "completed": "🏥",
            }.get(a["status"], "❓")
            st.write(f"{status_emoji} {a['status']}")
        with col5:
            if a["status"] in ("confirmed", "pending"):
                if st.button("取消", key=f"cancel_appt_{a['id']}"):
                    res = admin_cancel_appointment(
                        a["id"], reason="管理员取消"
                    )
                    if res["success"]:
                        st.success("已取消")
                        st.rerun()

# =====================================================================
# Tab 3: 医生管理
# =====================================================================
with tab_doc:
    st.subheader("医生列表")
    doc_repo = DoctorRepository(db)
    dept_repo = DepartmentRepository(db)

    doctors = doc_repo.list_all()
    st.write(f"共 {len(doctors)} 位医生")
    for d in doctors:
        col1, col2, col3 = st.columns([2, 2, 2])
        with col1:
            st.write(f"**{d['name']}**")
        with col2:
            st.write(f"{d['department']} · {d['title']}")
        with col3:
            st.caption(f"专长：{d.get('specialty', '')}")

    st.divider()
    st.subheader("新建医生")
    with st.form("new_doctor"):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            nd_name = st.text_input("姓名")
        with c2:
            dept_options = [d["name"] for d in dept_repo.list_all()]
            nd_dept = st.selectbox("科室", options=dept_options)
        with c3:
            nd_title = st.selectbox(
                "职称", options=["住院医师", "主治医师", "副主任医师", "主任医师"], index=1
            )
        with c4:
            nd_spec = st.text_input("专长（可选）")
        if st.form_submit_button("创建"):
            if not nd_name.strip():
                st.error("请输入姓名")
            else:
                res = admin_create_doctor(
                    name=nd_name.strip(),
                    department=nd_dept,
                    title=nd_title,
                    specialty=nd_spec,
                )
                if res["success"]:
                    st.success(f"✅ 已创建 doctor_id={res['doctor_id']}")
                    st.rerun()
                else:
                    st.error(res["error_message"])

# =====================================================================
# Tab 4: 审计日志
# =====================================================================
with tab_audit:
    st.subheader("最近操作")
    logs = admin_recent_audit_log(limit=50)
    for log in logs:
        with st.container():
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                st.code(log["event_type"], language="text")
            with col2:
                st.caption(f"actor: {log['actor']} · entity: {log['entity_type']}:{log['entity_id']}")
            with col3:
                st.caption(log["created_at"])
            if log.get("metadata"):
                st.caption(f"📋 {log['metadata']}")
            st.divider()
