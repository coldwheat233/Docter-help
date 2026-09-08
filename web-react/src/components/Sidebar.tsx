/** 左侧栏：病历夹（患者卡 + 我的预约） */

import { useCallback, useEffect, useState } from 'react'
import { fetchAppointments } from '../api'
import type { Appointment } from '../types'

interface Props {
  patientId: string
  refreshKey: number
}

const PATIENT = { id: 'P20240001', name: '张三', phone: '138****0001' }

const STATUS_STYLE: Record<string, { label: string; cls: string }> = {
  confirmed: { label: '已确认', cls: 'bg-dai-mist text-dai-deep' },
  pending: { label: '待确认', cls: 'bg-paper-deep text-ink-soft' },
  cancelled: { label: '已取消', cls: 'bg-seal/10 text-seal' },
  completed: { label: '已就诊', cls: 'bg-dai-mist text-dai-deep' },
  no_show: { label: '爽约', cls: 'bg-seal/10 text-seal' },
}

export default function Sidebar({ patientId, refreshKey }: Props) {
  const [appointments, setAppointments] = useState<Appointment[]>([])
  const [loading, setLoading] = useState(false)

  const patient = PATIENT

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await fetchAppointments(patientId)
      setAppointments(data.appointments ?? [])
    } catch {
      setAppointments([])
    } finally {
      setLoading(false)
    }
  }, [patientId])

  useEffect(() => {
    load()
  }, [load, refreshKey])

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

      {/* 就诊人卡（登录态展示，不可切换——真实系统来自登录） */}
      <div className="border-b border-dashed border-thread px-5 py-4">
        <p className="mb-2 font-serif-sc text-[11px] tracking-[0.3em] text-ink-faint">就诊人</p>
        <div className="rounded-sm border border-thread bg-paper px-3 py-2.5">
          <div className="flex items-center justify-between">
            <span className="font-serif-sc text-[15px] font-bold text-ink">{patient.name}</span>
            <span className="font-mono-id text-[10px] text-ink-faint">{patient.id}</span>
          </div>
          <p className="mt-0.5 font-mono-id text-[10px] text-ink-faint">{patient.phone}</p>
        </div>
      </div>

      {/* 我的预约 */}
      <div className="flex min-h-0 flex-1 flex-col px-5 py-4">
        <div className="mb-2 flex items-center justify-between">
          <p className="font-serif-sc text-[11px] tracking-[0.3em] text-ink-faint">
            预约记录 · {patient.name}
          </p>
          <button
            onClick={load}
            className="cursor-pointer font-mono-id text-[10px] text-dai hover:text-dai-deep"
            title="刷新"
          >
            {loading ? '…' : '↻'}
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
          {appointments.length === 0 && (
            <p className="mt-6 text-center text-xs leading-relaxed text-ink-faint">
              暂无预约记录
              <br />
              <span className="text-[11px] opacity-70">对助手说「我想挂号」试试</span>
            </p>
          )}
          {appointments.map((a) => {
            const st = STATUS_STYLE[a.status] ?? STATUS_STYLE.pending
            const id = a.appointment_id ?? a.id
            return (
              <div
                key={id}
                className="rounded-sm border border-thread/70 bg-paper px-3 py-2.5 transition-shadow hover:shadow-[2px_2px_0_rgba(28,26,22,0.08)]"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono-id text-[11px] font-semibold text-ink">{id}</span>
                  <span
                    className={`rounded-sm px-1.5 py-0.5 font-serif-sc text-[10px] tracking-wider ${st.cls}`}
                  >
                    {st.label}
                  </span>
                </div>
                {a.symptoms && (
                  <p className="mt-1 truncate text-[11.5px] text-ink-faint">主诉：{a.symptoms}</p>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* 底部署名 */}
      <div className="border-t border-thread px-5 py-3">
        <p className="font-mono-id text-[9.5px] leading-relaxed tracking-wider text-ink-faint/70">
          LANGGRAPH MULTI-AGENT
          <br />
          SUPERVISOR · HITL GATED
        </p>
      </div>
    </aside>
  )
}
