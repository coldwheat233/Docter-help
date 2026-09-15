/** 左侧栏：病历夹（就诊人卡 + 即将就诊 + 历史预约 + 病历资料 + 就诊摘要） */

import { useCallback, useEffect, useState } from 'react'
import { cancelAppointment, fetchAppointments, fetchDocuments, fetchSummary, type PatientDocument } from '../api'
import type { Appointment } from '../types'

interface Props {
  token: string
  patientId: string
  patientName: string
  onLogout: () => void
  refreshKey: number
  /** 点「改约」：由父组件打开排班面板（改约模式） */
  onReschedule: (a: Appointment) => void
}

const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  confirmed: { label: '已确认', cls: 'bg-dai-mist text-dai-deep' },
  pending: { label: '待确认', cls: 'bg-paper-deep text-ink-soft' },
  cancelled: { label: '已取消', cls: 'bg-seal/10 text-seal' },
  completed: { label: '已就诊', cls: 'bg-dai-mist text-dai-deep' },
  no_show: { label: '爽约', cls: 'bg-seal/10 text-seal' },
}

const SLOT_LABEL: Record<string, string> = {
  morning: '上午',
  afternoon: '下午',
  evening: '晚班',
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function fmtDate(iso?: string): { md: string; weekday: string } | null {
  if (!iso) return null
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!m) return null
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  return { md: `${Number(m[2])}月${Number(m[3])}日`, weekday: WEEKDAYS[d.getDay()] ?? '' }
}

function StatusBadge({ status }: { status: Appointment['status'] }) {
  const st = STATUS_STYLE[status] ?? STATUS_STYLE.pending
  return (
    <span className={`rounded-sm px-1.5 py-0.5 font-serif-sc text-[10px] tracking-wider ${st.cls}`}>
      {st.label}
    </span>
  )
}

function UpcomingCard({
  a,
  busy,
  onCancel,
  onReschedule,
}: {
  a: Appointment
  busy: boolean
  onCancel: (a: Appointment) => void
  onReschedule: (a: Appointment) => void
}) {
  const id = a.appointment_id ?? a.id
  const date = fmtDate(a.schedule_date)
  const slot = a.time_slot ? SLOT_LABEL[a.time_slot] ?? a.time_slot : ''
  const time = a.start_time && a.end_time ? ` ${a.start_time}-${a.end_time}` : ''
  return (
    <div className="rounded-sm border border-dai/40 bg-paper px-3 py-2.5 shadow-[2px_2px_0_rgba(28,26,22,0.06)]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-serif-sc text-[13px] font-bold text-ink">
          {date ? `${date.md} ${date.weekday}` : '日期待定'}
        </span>
        <StatusBadge status={a.status} />
      </div>
      <p className="mt-0.5 font-mono-id text-[10.5px] text-ink-soft">
        {slot}
        {time} · {a.department || '科室待定'}
      </p>
      {a.doctor_name && (
        <p className="mt-0.5 text-[11.5px] text-ink-soft">
          {a.doctor_name}
          {a.doctor_title ? `（${a.doctor_title}）` : ''}
        </p>
      )}
      {a.symptoms && <p className="mt-1 truncate text-[11px] text-ink-faint">主诉：{a.symptoms}</p>}
      <p className="mt-1 font-mono-id text-[9.5px] text-ink-faint/70">{id}</p>
      <div className="mt-2 flex gap-2 border-t border-dashed border-thread/60 pt-2">
        <button
          disabled={busy}
          onClick={() => onReschedule(a)}
          className="cursor-pointer rounded-sm border border-dai/60 px-2.5 py-1 font-serif-sc text-[10.5px] tracking-[0.15em] text-dai-deep transition-colors hover:bg-dai-mist disabled:opacity-40"
        >
          改约
        </button>
        <button
          disabled={busy}
          onClick={() => onCancel(a)}
          className="cursor-pointer rounded-sm border border-seal/40 px-2.5 py-1 font-serif-sc text-[10.5px] tracking-[0.15em] text-seal transition-colors hover:bg-seal/10 disabled:opacity-40"
        >
          取消
        </button>
      </div>
    </div>
  )
}

function HistoryRow({ a }: { a: Appointment }) {
  const id = a.appointment_id ?? a.id
  const date = fmtDate(a.schedule_date)
  return (
    <div className="border-b border-dashed border-thread/60 px-0.5 py-2 last:border-b-0">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono-id text-[11px] text-ink-soft">
          {date ? `${date.md}` : '—'}
          {a.department ? ` · ${a.department}` : ''}
        </span>
        <StatusBadge status={a.status} />
      </div>
      {(a.doctor_name || a.symptoms) && (
        <p className="mt-0.5 truncate text-[11px] text-ink-faint">
          {a.doctor_name}
          {a.doctor_name && a.symptoms ? '｜' : ''}
          {a.symptoms ? `主诉：${a.symptoms}` : ''}
        </p>
      )}
      {a.status === 'cancelled' && a.cancelled_reason && (
        <p className="mt-0.5 truncate text-[10.5px] text-seal/80">原因：{a.cancelled_reason}</p>
      )}
      <p className="mt-0.5 font-mono-id text-[9px] text-ink-faint/60">{id}</p>
    </div>
  )
}

/** 就诊摘要弹层 */
function SummaryModal({ token, onClose }: { token: string; onClose: () => void }) {
  const [text, setText] = useState('正在生成就诊摘要…')
  const [refreshing, setRefreshing] = useState(false)
  const load = useCallback(
    async (refresh = false) => {
      setRefreshing(true)
      try {
        const d = await fetchSummary(token, refresh)
        setText(d.summary)
      } catch (e) {
        setText(e instanceof Error ? `生成失败：${e.message}` : '生成失败')
      } finally {
        setRefreshing(false)
      }
    },
    [token],
  )
  useEffect(() => {
    load()
  }, [load])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-sm border-2 border-dai/50 bg-paper shadow-[6px_6px_0_rgba(28,26,22,0.25)]">
        <div className="flex items-center justify-between border-b border-thread px-5 py-3.5">
          <div>
            <h2 className="font-serif-sc text-base font-black tracking-[0.2em] text-dai-deep">
              就诊摘要
            </h2>
            <p className="font-mono-id text-[9.5px] uppercase tracking-[0.2em] text-ink-faint">
              For Doctor Review · 辅助归纳，非医学诊断
            </p>
          </div>
          <button
            onClick={onClose}
            className="cursor-pointer rounded-sm border border-thread px-3 py-1 font-serif-sc text-xs tracking-[0.25em] text-ink-faint transition-colors hover:border-seal hover:text-seal"
          >
            关闭
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-ink">{text}</p>
        </div>
        <div className="border-t border-thread px-5 py-2.5">
          <button
            onClick={() => load(true)}
            disabled={refreshing}
            className="cursor-pointer font-mono-id text-[10.5px] text-dai hover:text-dai-deep disabled:opacity-40"
          >
            {refreshing ? '重新生成中…' : '↻ 重新生成'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Sidebar({ token, patientId, patientName, onLogout, refreshKey, onReschedule }: Props) {
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [documents, setDocuments] = useState<PatientDocument[]>([])
  const [loading, setLoading] = useState(false)
  const [showHistory, setShowHistory] = useState(true)
  const [showDocs, setShowDocs] = useState(false)
  const [showSummary, setShowSummary] = useState(false)
  const [operating, setOperating] = useState<string | null>(null) // 正在取消/改约的预约号
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [appt, docs] = await Promise.allSettled([fetchAppointments(token), fetchDocuments(token)])
      setAppointments(appt.status === 'fulfilled' ? (appt.value.appointments ?? []) : [])
      setDocuments(docs.status === 'fulfilled' ? (docs.value.documents ?? []) : [])
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load, refreshKey])

  const handleCancel = useCallback(
    async (a: Appointment) => {
      const id = a.appointment_id ?? a.id
      if (!window.confirm(`确定取消预约 ${id}（${a.schedule_date ?? ''} ${a.department ?? ''}）吗？`)) return
      setOperating(id)
      setNotice('')
      try {
        await cancelAppointment(token, id, '患者主动取消')
        await load()
      } catch (e) {
        setNotice(e instanceof Error ? e.message : '取消失败')
      } finally {
        setOperating(null)
      }
    },
    [token, load],
  )

  // 后端已把 upcoming 排前面；这里按标记分组（旧数据没有标记时按状态兜底）
  const upcoming = appointments.filter(
    (a) => a.is_upcoming ?? (!a.is_past && (a.status === 'pending' || a.status === 'confirmed')),
  )
  const history = appointments.filter((a) => !upcoming.includes(a))

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-r border-thread bg-paper-deep/40">
      {/* 病历夹封面头 */}
      <div className="border-b border-thread px-5 pb-4 pt-5">
        <h1 className="font-serif-sc text-xl font-black tracking-[0.2em] text-dai-deep">
          云枢医院
        </h1>
        <p className="mt-0.5 font-mono-id text-[10px] uppercase tracking-[0.25em] text-ink-faint">
          Outpatient Records
        </p>
      </div>

      {/* 就诊人卡（登录态） */}
      <div className="border-b border-dashed border-thread px-5 py-4">
        <p className="mb-2 font-serif-sc text-[11px] tracking-[0.3em] text-ink-faint">就诊人</p>
        <div className="rounded-sm border border-thread bg-paper px-3 py-2.5">
          <div className="flex items-center justify-between">
            <span className="font-serif-sc text-[15px] font-bold text-ink">{patientName}</span>
            <span className="font-mono-id text-[10px] text-ink-faint">{patientId}</span>
          </div>
        </div>
        <button
          onClick={() => setShowSummary(true)}
          className="mt-2 w-full cursor-pointer rounded-sm border border-dai/50 px-3 py-1.5 font-serif-sc text-[11px] tracking-[0.2em] text-dai-deep transition-colors hover:bg-dai-mist"
        >
          📄 生成就诊摘要
        </button>
      </div>

      {/* 预约记录 + 病历资料 */}
      <div className="flex min-h-0 flex-1 flex-col px-5 py-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="font-serif-sc text-[11px] tracking-[0.3em] text-ink-faint">
            预约记录 · {patientName}
          </p>
          <button
            onClick={load}
            className="cursor-pointer font-mono-id text-[10px] text-dai hover:text-dai-deep"
            title="刷新"
          >
            {loading ? '…' : '↻'}
          </button>
        </div>

        {notice && <p className="mb-2 text-[11px] text-seal">{notice}</p>}

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
          {appointments.length === 0 && documents.length === 0 && (
            <p className="mt-6 text-center text-xs leading-relaxed text-ink-faint">
              暂无预约与病历
              <br />
              <span className="text-[11px] opacity-70">对助手说「我想挂号」，或点 📎 上传检查报告</span>
            </p>
          )}

          {/* 即将就诊 */}
          {upcoming.length > 0 && (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 font-serif-sc text-[10.5px] tracking-[0.25em] text-dai-deep">
                <span className="inline-block h-1 w-1 rounded-full bg-dai" />
                即将就诊 · {upcoming.length}
              </p>
              <div className="space-y-2">
                {upcoming.map((a) => {
                  const id = a.appointment_id ?? a.id
                  return (
                    <UpcomingCard
                      key={id}
                      a={a}
                      busy={operating === id}
                      onCancel={handleCancel}
                      onReschedule={onReschedule}
                    />
                  )
                })}
              </div>
            </div>
          )}

          {/* 历史记录 */}
          {history.length > 0 && (
            <div>
              <button
                onClick={() => setShowHistory((v) => !v)}
                className="mb-1 flex w-full cursor-pointer items-center gap-1.5 text-left font-serif-sc text-[10.5px] tracking-[0.25em] text-ink-faint transition-colors hover:text-ink-soft"
              >
                <span
                  className={`inline-block transition-transform ${showHistory ? 'rotate-90' : ''}`}
                >
                  ▸
                </span>
                历史记录 · {history.length}
              </button>
              {showHistory && (
                <div className="rounded-sm border border-thread/60 bg-paper/50 px-2">
                  {history.map((a) => {
                    const id = a.appointment_id ?? a.id
                    return <HistoryRow key={id} a={a} />
                  })}
                </div>
              )}
            </div>
          )}

          {/* 病历资料（上传的检查报告等） */}
          {documents.length > 0 && (
            <div>
              <button
                onClick={() => setShowDocs((v) => !v)}
                className="mb-1 flex w-full cursor-pointer items-center gap-1.5 text-left font-serif-sc text-[10.5px] tracking-[0.25em] text-ink-faint transition-colors hover:text-ink-soft"
              >
                <span className={`inline-block transition-transform ${showDocs ? 'rotate-90' : ''}`}>
                  ▸
                </span>
                病历资料 · {documents.length}
              </button>
              {showDocs && (
                <div className="space-y-1.5">
                  {documents.map((d) => (
                    <div key={d.id} className="rounded-sm border border-thread/60 bg-paper/50 px-2.5 py-1.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate font-serif-sc text-[11.5px] font-bold text-ink">
                          {d.title || '未命名资料'}
                        </span>
                        <span className="shrink-0 rounded-sm bg-paper-deep px-1 py-0.5 font-mono-id text-[9px] text-ink-soft">
                          {d.doc_type}
                        </span>
                      </div>
                      {d.summary && (
                        <p className="mt-0.5 line-clamp-2 text-[10.5px] leading-relaxed text-ink-faint">
                          {d.summary}
                        </p>
                      )}
                      <p className="mt-0.5 font-mono-id text-[9px] text-ink-faint/60">
                        {String(d.created_at).slice(0, 16)}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 底部：退出 + 署名 */}
      <div className="border-t border-thread px-5 py-3">
        <button
          onClick={onLogout}
          className="mb-2 w-full cursor-pointer rounded-sm border border-thread px-3 py-1.5 font-serif-sc text-[11px] tracking-[0.25em] text-ink-faint transition-colors hover:border-seal hover:text-seal"
        >
          退出登录
        </button>
        <p className="font-mono-id text-[9.5px] leading-relaxed tracking-wider text-ink-faint/70">
          LANGGRAPH MULTI-AGENT
          <br />
          SUPERVISOR · HITL GATED
        </p>
      </div>

      {showSummary && <SummaryModal token={token} onClose={() => setShowSummary(false)} />}
    </aside>
  )
}
