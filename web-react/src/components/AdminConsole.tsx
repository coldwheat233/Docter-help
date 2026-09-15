/** 业务中台：一页式运营仪表盘（KPI + 图表 + 实时审批 + 排班可视化 + 检索 + 审计） */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  adminApi,
  type AdminAppointmentRow,
  type AdminScheduleItem,
  type ApprovalItem,
} from '../api'

interface Props {
  token: string
  staffName: string
  onLogout: () => void
}

const SLOT_LABEL: Record<string, string> = { morning: '上午', afternoon: '下午', evening: '晚班' }
const SEVERITY_LABEL: Record<string, string> = { mild: '轻微', moderate: '中度', severe: '剧烈' }
const TYPE_LABEL: Record<string, string> = {
  appointment_create: '预约申请',
  appointment_cancel: '取消申请',
  appointment_reschedule: '改约申请',
}
const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

/* 图表配色（与「数字病历夹」设计系统同源） */
const C = {
  dai: '#1f5c5a',
  daiMist: '#e3edec',
  seal: '#b03a2e',
  amber: '#c08a2d',
  blue: '#4a6b8a',
  gray: '#8a8577',
  ink: '#1c1a16',
}

const STATUS_META: Record<string, { label: string; color: string }> = {
  confirmed: { label: '已确认', color: C.dai },
  pending: { label: '待确认', color: C.amber },
  completed: { label: '已就诊', color: C.blue },
  cancelled: { label: '已取消', color: C.seal },
  no_show: { label: '爽约', color: C.gray },
}

function todayIso(offset = 0): string {
  const d = new Date()
  d.setDate(d.getDate() + offset)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function dayLabel(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return iso
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const wd = WEEKDAYS[d.getDay()] ?? ''
  if (iso === todayIso()) return `今天 ${wd}`
  if (iso === todayIso(1)) return `明天 ${wd}`
  return `${Number(m[2])}/${Number(m[3])} ${wd}`
}

/* ============ 图表（零依赖 SVG/CSS） ============ */

function DonutChart({ data }: { data: { label: string; value: number; color: string }[] }) {
  const total = data.reduce((s, d) => s + d.value, 0)
  const r = 45
  const circumference = 2 * Math.PI * r
  let offset = 0
  return (
    <div className="flex items-center gap-4">
      <svg width="128" height="128" viewBox="0 0 128 128" className="shrink-0">
        <circle cx="64" cy="64" r={r} fill="none" stroke={C.daiMist} strokeWidth="16" />
        {total > 0 &&
          data
            .filter((d) => d.value > 0)
            .map((d) => {
              const len = (d.value / total) * circumference
              const el = (
                <circle
                  key={d.label}
                  cx="64"
                  cy="64"
                  r={r}
                  fill="none"
                  stroke={d.color}
                  strokeWidth="16"
                  strokeDasharray={`${len} ${circumference - len}`}
                  strokeDashoffset={-offset}
                  transform="rotate(-90 64 64)"
                >
                  <title>{`${d.label}: ${d.value}`}</title>
                </circle>
              )
              offset += len
              return el
            })}
        <text x="64" y="60" textAnchor="middle" fontSize="22" fontWeight="800" fill={C.ink} fontFamily="serif">
          {total}
        </text>
        <text x="64" y="78" textAnchor="middle" fontSize="9" fill={C.gray} letterSpacing="1">
          总预约
        </text>
      </svg>
      <div className="space-y-1.5">
        {data.map((d) => (
          <div key={d.label} className="flex items-center gap-2 text-[11.5px] text-ink-soft">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: d.color }} />
            {d.label}
            <span className="font-mono-id font-bold text-ink">{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function StackBars({
  data,
}: {
  data: { label: string; booked: number; remaining: number }[]
}) {
  const max = Math.max(1, ...data.map((d) => d.booked + d.remaining))
  return (
    <div>
      <div className="flex h-36 items-end gap-2">
        {data.map((d) => {
          const totalH = ((d.booked + d.remaining) / max) * 100
          const bookedH = d.booked + d.remaining > 0 ? (d.booked / (d.booked + d.remaining)) * totalH : 0
          return (
            <div key={d.label} className="flex min-w-0 flex-1 flex-col items-center gap-1">
              <span className="font-mono-id text-[9px] text-ink-soft">{d.booked + d.remaining}</span>
              <div
                className="flex w-full max-w-9 flex-col justify-end overflow-hidden rounded-t-sm"
                style={{ height: `${Math.max(totalH, 2)}%` }}
                title={`${d.label}：已约 ${d.booked} / 可约 ${d.remaining}`}
              >
                <div style={{ height: `${totalH > 0 ? (bookedH / totalH) * 100 : 0}%`, background: C.seal, opacity: 0.75 }} />
                <div style={{ height: `${totalH > 0 ? 100 - (bookedH / totalH) * 100 : 0}%`, background: C.dai, opacity: 0.8 }} />
              </div>
              <span className="w-full truncate text-center font-mono-id text-[9px] text-ink-faint">{d.label}</span>
            </div>
          )
        })}
      </div>
      <div className="mt-2 flex justify-center gap-4 text-[10.5px] text-ink-soft">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5" style={{ background: C.seal, opacity: 0.75 }} />已约
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5" style={{ background: C.dai, opacity: 0.8 }} />可约
        </span>
      </div>
    </div>
  )
}

function HBars({ data }: { data: { label: string; value: number }[] }) {
  const max = Math.max(1, ...data.map((d) => d.value))
  return (
    <div className="space-y-2">
      {data.map((d) => (
        <div key={d.label} className="flex items-center gap-2">
          <span className="w-14 shrink-0 truncate text-right text-[11px] text-ink-soft">{d.label}</span>
          <div className="h-4 min-w-0 flex-1 overflow-hidden rounded-sm bg-dai-mist">
            <div
              className="flex h-full items-center justify-end rounded-sm px-1.5"
              style={{ width: `${Math.max((d.value / max) * 100, 8)}%`, background: C.dai, opacity: 0.85 }}
            >
              <span className="font-mono-id text-[9.5px] font-bold text-paper">{d.value}</span>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

/* ============ 小组件 ============ */

function KpiCard({ label, value, accent }: { label: string; value: number | string; accent?: boolean }) {
  return (
    <div
      className={`rounded-sm border px-3 py-2.5 ${
        accent ? 'border-dai/50 bg-dai-mist/50' : 'border-thread bg-paper'
      }`}
    >
      <p className="truncate font-mono-id text-[9.5px] uppercase tracking-[0.15em] text-ink-faint">{label}</p>
      <p className={`mt-0.5 font-serif-sc text-xl font-black ${accent ? 'text-dai-deep' : 'text-ink'}`}>{value}</p>
    </div>
  )
}

function SectionTitle({ children, extra }: { children: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between">
      <h3 className="flex items-center gap-2 font-serif-sc text-[13px] font-bold tracking-[0.2em] text-ink">
        <span className="inline-block h-3.5 w-0.5 bg-dai" />
        {children}
      </h3>
      {extra}
    </div>
  )
}

/* ============ 主控制台 ============ */

export default function AdminConsole({ token, staffName, onLogout }: Props) {
  const [approvals, setApprovals] = useState<ApprovalItem[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [schedules, setSchedules] = useState<AdminScheduleItem[]>([])
  const [apptRows, setApptRows] = useState<AdminAppointmentRow[]>([])
  const [doctors, setDoctors] = useState<{ id: number; name: string; department: string; title: string }[]>([])
  const [audit, setAudit] = useState<Record<string, unknown>[]>([])
  const [showAudit, setShowAudit] = useState(false)
  const [loading, setLoading] = useState(false)
  const [busyThread, setBusyThread] = useState<string | null>(null)
  const [notice, setNotice] = useState('')

  // 检索
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const qTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 排班视图
  const [departments, setDepartments] = useState<string[]>([])
  const [dept, setDept] = useState<string | null>(null)
  const [docFilter, setDocFilter] = useState('')

  // 排班管理表单
  const [doctorId, setDoctorId] = useState('')
  const [scheduleDate, setScheduleDate] = useState('')
  const [slot, setSlot] = useState<'morning' | 'afternoon' | 'evening'>('morning')
  const [capacity, setCapacity] = useState('20')
  const [schedMsg, setSchedMsg] = useState('')

  const loadCore = useCallback(async () => {
    setLoading(true)
    try {
      const [st, sv, dr, dp] = await Promise.all([
        adminApi.stats(token),
        adminApi.schedulesView(token, null, 7), // 图表/KPI 恒用全局视角
        adminApi.doctors(token),
        fetch('/api/departments').then((r) => r.json()) as Promise<{ departments: { name: string }[] }>,
      ])
      setStats(st)
      setSchedules(sv.schedules ?? [])
      const dl = dr.doctors ?? []
      setDoctors(dl)
      if (dl.length > 0 && !doctorId) setDoctorId(String(dl[0].id))
      const names = (dp.departments ?? []).map((x) => x.name)
      setDepartments(names)
      if (names.length > 0 && !dept) setDept(names[0])
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  const loadAppointments = useCallback(async () => {
    try {
      const d = await adminApi.searchAppointments(token, q, statusFilter)
      setApptRows(d.appointments ?? [])
    } catch {
      /* 保留旧数据 */
    }
  }, [token, q, statusFilter])

  const loadAudit = useCallback(async () => {
    try {
      const d = await adminApi.audit(token, 30)
      setAudit(d.audit ?? [])
    } catch {
      /* ignore */
    }
  }, [token])

  useEffect(() => {
    loadCore()
  }, [loadCore])

  useEffect(() => {
    loadAppointments()
  }, [loadAppointments])

  // 检索防抖
  useEffect(() => {
    if (qTimer.current) clearTimeout(qTimer.current)
    qTimer.current = setTimeout(() => loadAppointments(), 350)
    return () => {
      if (qTimer.current) clearTimeout(qTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, statusFilter])

  // 实时推送：审批队列 SSE
  useEffect(() => {
    const es = new EventSource(`/api/admin/approvals/stream?token=${encodeURIComponent(token)}`)
    es.addEventListener('approvals', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data)
        setApprovals(d.approvals ?? [])
      } catch {
        /* ignore */
      }
    })
    return () => es.close()
  }, [token])

  const decide = useCallback(
    async (threadId: string, decision: string) => {
      setBusyThread(threadId)
      setNotice('')
      try {
        await adminApi.decide(token, threadId, decision)
        setApprovals((prev) => prev.filter((a) => a.thread_id !== threadId))
        setNotice(decision === 'approve' ? '已核准，预约落库成功' : '已驳回')
        loadCore()
        loadAppointments()
      } catch (e) {
        setNotice(e instanceof Error ? e.message : '处理失败')
      } finally {
        setBusyThread(null)
      }
    },
    [token, loadCore, loadAppointments],
  )

  const submitSchedule = useCallback(async () => {
    setSchedMsg('')
    try {
      const r = await adminApi.createSchedule(token, {
        doctor_id: Number(doctorId),
        schedule_date: scheduleDate,
        time_slot: slot,
        capacity: Number(capacity) || 20,
      })
      setSchedMsg(r.success ? `✅ 排班已创建（schedule_id ${r.schedule_id}）` : `❌ ${r.error_message ?? '创建失败'}`)
      if (r.success) loadCore()
    } catch (e) {
      setSchedMsg(`❌ ${e instanceof Error ? e.message : '创建失败'}`)
    }
  }, [token, doctorId, scheduleDate, slot, capacity, loadCore])

  /* ---- 派生数据 ---- */
  const statusDist = useMemo(() => {
    const count: Record<string, number> = {}
    for (const a of apptRows) count[a.status] = (count[a.status] ?? 0) + 1
    return Object.entries(STATUS_META).map(([k, m]) => ({
      label: m.label,
      value: count[k] ?? 0,
      color: m.color,
    }))
  }, [apptRows])

  const sevenDayBars = useMemo(() => {
    const byDate: Record<string, { booked: number; remaining: number }> = {}
    for (let i = 0; i < 7; i++) byDate[todayIso(i)] = { booked: 0, remaining: 0 }
    for (const s of schedules) {
      const b = byDate[s.schedule_date]
      if (!b) continue
      b.remaining += s.remaining
      b.booked += Math.max(0, s.capacity - s.remaining)
    }
    return Object.entries(byDate).map(([iso, v]) => ({ label: dayLabel(iso).replace(' ', '\n'), ...v }))
  }, [schedules])

  const deptBars = useMemo(() => {
    const byDept: Record<string, number> = {}
    for (const s of schedules) byDept[s.department] = (byDept[s.department] ?? 0) + s.remaining
    return Object.entries(byDept)
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value)
  }, [schedules])

  const sevenDaySource = useMemo(
    () => schedules.reduce((s, x) => s + x.remaining, 0),
    [schedules],
  )

  // 排班网格：科室 chips + 医生搜索都只过滤网格（图表/KPI 保持全局视角）
  const gridDays = useMemo(() => Array.from({ length: 7 }, (_, i) => todayIso(i)), [])
  const doctorGroups = useMemo(() => {
    const kw = docFilter.trim()
    const filtered = schedules.filter((s) => {
      if (dept && s.department !== dept) return false
      if (kw && !(s.doctor_name.includes(kw) || s.department.includes(kw))) return false
      return true
    })
    const map = new Map<number, { name: string; title: string; dept: string; cells: Map<string, AdminScheduleItem[]> }>()
    for (const it of filtered) {
      let g = map.get(it.doctor_id)
      if (!g) {
        g = { name: it.doctor_name, title: it.doctor_title ?? '', dept: it.department, cells: new Map() }
        map.set(it.doctor_id, g)
      }
      const list = g.cells.get(it.schedule_date) ?? []
      list.push(it)
      g.cells.set(it.schedule_date, list)
    }
    return [...map.values()]
  }, [schedules, docFilter, dept])

  return (
    <div className="flex h-full flex-col bg-paper">
      {/* 顶栏 */}
      <header className="flex items-center justify-between border-b-2 border-ink/70 bg-paper-deep/40 px-6 py-3">
        <div>
          <h1 className="font-serif-sc text-lg font-black tracking-[0.25em] text-ink">
            云枢医院 · 业务中台
          </h1>
          <p className="font-mono-id text-[10px] uppercase tracking-[0.25em] text-ink-faint">
            Operations Console · Staff Only
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-mono-id text-[11px] text-ink-soft">{staffName}</span>
          <button
            onClick={() => {
              loadCore()
              loadAppointments()
              loadAudit()
            }}
            className="cursor-pointer rounded-sm border border-thread px-3 py-1.5 font-mono-id text-[10.5px] text-dai hover:text-dai-deep"
          >
            {loading ? '加载中…' : '↻ 全局刷新'}
          </button>
          <button
            onClick={onLogout}
            className="cursor-pointer rounded-sm border border-thread px-3 py-1.5 font-serif-sc text-[11px] tracking-[0.25em] text-ink-faint transition-colors hover:border-seal hover:text-seal"
          >
            退出
          </button>
        </div>
      </header>

      <main className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-4">
        {notice && (
          <p className="rounded-sm border border-dai/40 bg-dai-mist/50 px-3 py-2 text-xs text-dai-deep">{notice}</p>
        )}

        {/* KPI */}
        <div className="grid grid-cols-4 gap-2.5 sm:grid-cols-8">
          <KpiCard label="待审批" value={approvals.length} accent />
          <KpiCard label="总预约" value={stats.total_appointments ?? '-'} />
          <KpiCard label="已确认" value={stats.confirmed ?? '-'} />
          <KpiCard label="已取消" value={stats.cancelled ?? '-'} />
          <KpiCard label="已就诊" value={stats.completed ?? '-'} />
          <KpiCard label="7天可约号源" value={sevenDaySource} accent />
          <KpiCard label="医生" value={stats.total_doctors ?? '-'} />
          <KpiCard label="患者" value={stats.total_patients ?? '-'} />
        </div>

        {/* 图表行 */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="rounded-sm border border-thread bg-paper px-4 py-3">
            <SectionTitle>预约状态分布</SectionTitle>
            <DonutChart data={statusDist} />
            <p className="mt-1 font-mono-id text-[9px] text-ink-faint/70">
              基于当前检索范围（{apptRows.length} 条）
            </p>
          </div>
          <div className="rounded-sm border border-thread bg-paper px-4 py-3">
            <SectionTitle>未来 7 天号源（已约 / 可约）</SectionTitle>
            <StackBars data={sevenDayBars} />
          </div>
          <div className="rounded-sm border border-thread bg-paper px-4 py-3">
            <SectionTitle>各科室 7 天可约号源</SectionTitle>
            {deptBars.length > 0 ? (
              <HBars data={deptBars} />
            ) : (
              <p className="py-8 text-center text-xs text-ink-faint">暂无数据</p>
            )}
          </div>
        </div>

        {/* 待审批（实时） */}
        <section>
          <SectionTitle extra={<span className="font-mono-id text-[10px] text-dai">● LIVE · SSE 实时推送</span>}>
            待审批 · {approvals.length}
          </SectionTitle>
          {approvals.length === 0 ? (
            <p className="rounded-sm border border-dashed border-thread px-4 py-4 text-center text-xs text-ink-faint">
              暂无待审批申请——患者提交后会实时出现在这里
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 xl:grid-cols-3">
              {approvals.map((a) => (
                <ApprovalMini
                  key={a.thread_id}
                  item={a}
                  busy={busyThread === a.thread_id}
                  onDecide={decide}
                />
              ))}
            </div>
          )}
        </section>

        {/* 排班可视化 */}
        <section>
          <SectionTitle
            extra={
              <input
                value={docFilter}
                onChange={(e) => setDocFilter(e.target.value)}
                placeholder="搜索医生 / 科室…"
                className="w-44 rounded-sm border border-thread bg-paper-deep/30 px-2.5 py-1 text-[11px] text-ink outline-none focus:border-dai"
              />
            }
          >
            排班可视化 · 未来 7 天（含满员）
          </SectionTitle>
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            {departments.map((name) => (
              <button
                key={name}
                onClick={() => setDept(name)}
                className={`cursor-pointer rounded-sm border px-2.5 py-1 font-serif-sc text-[11px] tracking-[0.15em] transition-colors ${
                  dept === name
                    ? 'border-dai bg-dai-mist font-bold text-dai-deep'
                    : 'border-thread text-ink-soft hover:border-dai'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
          <div className="space-y-2">
            {doctorGroups.length === 0 && (
              <p className="rounded-sm border border-dashed border-thread px-4 py-4 text-center text-xs text-ink-faint">
                没有匹配的排班
              </p>
            )}
            {doctorGroups.map((g) => (
              <div key={g.name + g.dept} className="rounded-sm border border-thread bg-paper px-3 py-2.5">
                <div className="mb-1.5 flex items-baseline gap-2">
                  <span className="font-serif-sc text-[13px] font-bold text-ink">{g.name}</span>
                  {g.title && <span className="font-serif-sc text-[10.5px] text-ink-faint">{g.title}</span>}
                  <span className="font-mono-id text-[9.5px] text-ink-faint/70">{g.dept}</span>
                </div>
                <div className="grid grid-cols-7 gap-1.5">
                  {gridDays.map((d) => {
                    const cells = g.cells.get(d) ?? []
                    return (
                      <div key={d} className="min-w-0">
                        <p
                          className={`mb-1 text-center font-mono-id text-[9px] ${
                            d === todayIso() ? 'font-bold text-dai-deep' : 'text-ink-faint'
                          }`}
                        >
                          {dayLabel(d)}
                        </p>
                        <div className="space-y-1">
                          {cells.length === 0 && (
                            <div className="rounded-sm border border-dashed border-thread/50 py-1 text-center text-[10px] text-ink-faint/40">
                              —
                            </div>
                          )}
                          {cells.map((s) => {
                            const ratio = s.capacity > 0 ? s.remaining / s.capacity : 0
                            const color =
                              s.remaining === 0
                                ? { bg: C.seal, opacity: 0.12, text: C.seal, border: C.seal }
                                : ratio <= 0.4
                                  ? { bg: C.amber, opacity: 0.12, text: C.amber, border: C.amber }
                                  : { bg: C.daiMist, opacity: 1, text: C.dai, border: C.dai }
                            return (
                              <div
                                key={s.schedule_id}
                                title={`${SLOT_LABEL[s.time_slot]} ${s.start_time}-${s.end_time}｜剩 ${s.remaining}/${s.capacity}`}
                                className="rounded-sm border px-1 py-0.5 text-center"
                                style={{
                                  background: color.bg,
                                  opacity: color.opacity === 1 ? undefined : 1,
                                  borderColor: color.border,
                                }}
                              >
                                <span
                                  className="block font-serif-sc text-[10px] font-bold"
                                  style={{ color: s.remaining === 0 ? C.seal : C.ink }}
                                >
                                  {SLOT_LABEL[s.time_slot] ?? s.time_slot}
                                  {s.remaining === 0 ? ' 满' : ` 剩${s.remaining}`}
                                </span>
                                <span className="block font-mono-id text-[8.5px]" style={{ color: color.text }}>
                                  {s.remaining}/{s.capacity}
                                </span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 预约检索 */}
        <section>
          <SectionTitle extra={<span className="font-mono-id text-[10px] text-ink-faint">{apptRows.length} 条结果</span>}>
            预约检索
          </SectionTitle>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="关键词：预约号 / 患者 / 医生 / 科室 / 症状 / 日期…"
              className="min-w-72 flex-1 rounded-sm border border-thread bg-paper-deep/30 px-3 py-1.5 text-xs text-ink outline-none focus:border-dai"
            />
            <div className="flex gap-1.5">
              <button
                onClick={() => setStatusFilter('')}
                className={`cursor-pointer rounded-sm border px-2 py-1 text-[10.5px] transition-colors ${
                  statusFilter === '' ? 'border-ink bg-ink text-paper' : 'border-thread text-ink-soft'
                }`}
              >
                全部
              </button>
              {Object.entries(STATUS_META).map(([k, m]) => (
                <button
                  key={k}
                  onClick={() => setStatusFilter(k)}
                  className={`cursor-pointer rounded-sm border px-2 py-1 text-[10.5px] transition-colors ${
                    statusFilter === k ? 'text-paper' : 'border-thread text-ink-soft'
                  }`}
                  style={
                    statusFilter === k
                      ? { background: m.color, borderColor: m.color }
                      : undefined
                  }
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto rounded-sm border border-thread bg-paper">
            <table className="w-full text-left text-[11.5px]">
              <thead>
                <tr className="border-b border-thread bg-paper-deep/40 font-mono-id text-[9.5px] uppercase tracking-wider text-ink-faint">
                  <th className="px-2.5 py-2">预约号</th>
                  <th className="px-2.5 py-2">患者</th>
                  <th className="px-2.5 py-2">状态</th>
                  <th className="px-2.5 py-2">就诊</th>
                  <th className="px-2.5 py-2">时段</th>
                  <th className="px-2.5 py-2">科室 / 医生</th>
                  <th className="px-2.5 py-2">主诉</th>
                  <th className="px-2.5 py-2">提交时间</th>
                </tr>
              </thead>
              <tbody>
                {apptRows.map((a) => {
                  const meta = STATUS_META[a.status] ?? STATUS_META.pending
                  return (
                    <tr key={a.id} className="border-b border-dashed border-thread/50 text-ink-soft hover:bg-paper-deep/30">
                      <td className="px-2.5 py-1.5 font-mono-id text-[10px] text-ink">{a.id}</td>
                      <td className="px-2.5 py-1.5">{a.patient_name ?? '—'}</td>
                      <td className="px-2.5 py-1.5">
                        <span
                          className="rounded-sm px-1.5 py-0.5 font-serif-sc text-[10px]"
                          style={{ background: `${meta.color}1f`, color: meta.color }}
                        >
                          {meta.label}
                        </span>
                      </td>
                      <td className="px-2.5 py-1.5 font-mono-id text-[10.5px]">{a.schedule_date}</td>
                      <td className="px-2.5 py-1.5">
                        {SLOT_LABEL[a.time_slot] ?? a.time_slot} {a.start_time}-{a.end_time}
                      </td>
                      <td className="px-2.5 py-1.5">
                        {a.department} / {a.doctor_name}
                      </td>
                      <td className="max-w-40 truncate px-2.5 py-1.5">{a.symptoms || '—'}</td>
                      <td className="px-2.5 py-1.5 font-mono-id text-[9.5px]">
                        {String(a.created_at).slice(0, 16)}
                      </td>
                    </tr>
                  )
                })}
                {apptRows.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-3 py-6 text-center text-ink-faint">
                      没有匹配的预约记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* 排班管理 + 审计 */}
        <div className="grid grid-cols-1 gap-4 pb-4 lg:grid-cols-2">
          <div className="rounded-sm border border-thread bg-paper px-4 py-3">
            <SectionTitle>排班管理 · 新增</SectionTitle>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <label className="flex flex-col gap-1">
                <span className="text-ink-faint">医生</span>
                <select
                  value={doctorId}
                  onChange={(e) => setDoctorId(e.target.value)}
                  className="rounded-sm border border-thread bg-paper-deep/30 px-2 py-1.5 text-ink outline-none focus:border-dai"
                >
                  {doctors.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}（{d.department}，{d.title}）#{d.id}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-ink-faint">日期</span>
                <input
                  type="date"
                  value={scheduleDate}
                  onChange={(e) => setScheduleDate(e.target.value)}
                  className="rounded-sm border border-thread bg-paper-deep/30 px-2 py-1.5 text-ink outline-none focus:border-dai"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-ink-faint">时段</span>
                <select
                  value={slot}
                  onChange={(e) => setSlot(e.target.value as typeof slot)}
                  className="rounded-sm border border-thread bg-paper-deep/30 px-2 py-1.5 text-ink outline-none focus:border-dai"
                >
                  <option value="morning">上午</option>
                  <option value="afternoon">下午</option>
                  <option value="evening">晚班</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-ink-faint">号源容量</span>
                <input
                  value={capacity}
                  onChange={(e) => setCapacity(e.target.value)}
                  className="rounded-sm border border-thread bg-paper-deep/30 px-2 py-1.5 text-ink outline-none focus:border-dai"
                />
              </label>
            </div>
            <button
              disabled={!scheduleDate || !doctorId}
              onClick={submitSchedule}
              className="mt-3 cursor-pointer rounded-sm border-2 border-dai px-4 py-1.5 font-serif-sc text-xs font-bold tracking-[0.2em] text-dai-deep transition-colors hover:bg-dai hover:text-paper disabled:opacity-40"
            >
              创建排班
            </button>
            {schedMsg && <p className="mt-2 text-xs text-ink-soft">{schedMsg}</p>}
          </div>

          <div className="rounded-sm border border-thread bg-paper px-4 py-3">
            <SectionTitle
              extra={
                <button
                  onClick={() => {
                    setShowAudit((v) => !v)
                    if (!showAudit && audit.length === 0) loadAudit()
                  }}
                  className="cursor-pointer font-mono-id text-[10px] text-dai hover:text-dai-deep"
                >
                  {showAudit ? '收起' : '展开'}
                </button>
              }
            >
              审计日志
            </SectionTitle>
            {showAudit ? (
              <div className="max-h-56 space-y-1 overflow-y-auto font-mono-id text-[10px] text-ink-soft">
                {audit.map((a, i) => (
                  <p key={i} className="truncate border-b border-dashed border-thread/40 pb-1">
                    {String(a.created_at ?? '').slice(0, 19)} · {String(a.event_type ?? '')} ·{' '}
                    {String(a.entity_type ?? '')}#{String(a.entity_id ?? '')} · {String(a.actor ?? '')}
                  </p>
                ))}
                {audit.length === 0 && <p className="text-ink-faint">暂无记录</p>}
              </div>
            ) : (
              <p className="text-[11px] text-ink-faint">所有写操作（创建/取消/改约/中台处理）自动留痕</p>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

/* ============ 审批迷你卡 ============ */

function ApprovalMini({
  item,
  busy,
  onDecide,
}: {
  item: ApprovalItem
  busy: boolean
  onDecide: (threadId: string, decision: string) => void
}) {
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')
  return (
    <div className="rounded-sm border border-dai/40 bg-paper px-3 py-2.5 shadow-[2px_2px_0_rgba(28,26,22,0.06)]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-serif-sc text-[13px] font-bold text-ink">{item.patient_name}</span>
        <span className="rounded-sm bg-paper-deep px-1.5 py-0.5 font-mono-id text-[9px] text-ink-soft">
          {TYPE_LABEL[item.type] ?? item.type}
        </span>
      </div>
      <p className="mt-0.5 text-[11.5px] text-ink-soft">
        {item.schedule_date || '—'} · {item.time_slot ? (SLOT_LABEL[item.time_slot] ?? item.time_slot) : '—'}
        {item.severity ? ` · ${SEVERITY_LABEL[item.severity] ?? item.severity}` : ''}
      </p>
      {item.symptoms && <p className="mt-0.5 truncate text-[11px] text-ink-faint">主诉：{item.symptoms}</p>}
      <div className="mt-2 flex items-center gap-2">
        {!rejecting ? (
          <>
            <button
              disabled={busy}
              onClick={() => onDecide(item.thread_id, 'approve')}
              className="cursor-pointer rounded-sm border border-dai bg-dai-mist px-3 py-1 font-serif-sc text-[10.5px] font-bold tracking-[0.15em] text-dai-deep transition-colors hover:bg-dai hover:text-paper disabled:opacity-40"
            >
              ✓ 核准
            </button>
            <button
              disabled={busy}
              onClick={() => setRejecting(true)}
              className="cursor-pointer rounded-sm border border-seal/50 px-3 py-1 font-serif-sc text-[10.5px] tracking-[0.15em] text-seal transition-colors hover:bg-seal hover:text-paper disabled:opacity-40"
            >
              驳回
            </button>
          </>
        ) : (
          <>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="驳回原因"
              className="min-w-0 flex-1 rounded-sm border border-thread bg-paper-deep/30 px-2 py-1 text-[11px] outline-none focus:border-seal"
            />
            <button
              disabled={busy || !reason.trim()}
              onClick={() => onDecide(item.thread_id, `reject:${reason.trim()}`)}
              className="cursor-pointer rounded-sm bg-seal px-2.5 py-1 font-serif-sc text-[10.5px] font-bold text-paper disabled:opacity-40"
            >
              确认
            </button>
          </>
        )}
      </div>
    </div>
  )
}
