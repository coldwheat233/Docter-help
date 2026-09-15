/** 排班面板：未过期号源可视化，患者点选直约/改约（选完自动进入确认流程） */

import { useCallback, useEffect, useState } from 'react'
import { fetchDepartments, fetchSchedules, rescheduleAppointment, selectSlot } from '../api'
import type { ScheduleItem } from '../types'

interface Props {
  token: string
  threadId: string | null
  /** 改约模式：传入要改约的预约号（选中时段后走 /reschedule 而不是新建预约） */
  rescheduleId?: string | null
  onClose: () => void
  /** 选号成功（新建预约）：父组件接管 thread_id 并自动发确认消息 */
  onSelected: (threadId: string, summary: string) => void
  /** 改约成功 */
  onRescheduled?: (summary: string) => void
}

const SLOT_LABEL: Record<string, string> = {
  morning: '上午',
  afternoon: '下午',
  evening: '晚班',
}

const WEEKDAYS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

function dayLabel(dateIso: string, todayIso: string, tomorrowIso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateIso)
  if (!m) return dateIso
  const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const wd = WEEKDAYS[d.getDay()] ?? ''
  if (dateIso === todayIso) return `今天 ${wd}`
  if (dateIso === tomorrowIso) return `明天 ${wd}`
  return `${Number(m[2])}/${Number(m[3])} ${wd}`
}

interface DoctorGroup {
  doctorId: number
  doctorName: string
  doctorTitle: string
  days: Map<string, ScheduleItem[]> // date → slots（一格可能上午下午都有）
}

export default function SchedulePanel({
  token,
  threadId,
  rescheduleId,
  onClose,
  onSelected,
  onRescheduled,
}: Props) {
  const [departments, setDepartments] = useState<string[]>([])
  const [dept, setDept] = useState<string | null>(null)
  const [items, setItems] = useState<ScheduleItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [picking, setPicking] = useState<number | null>(null) // 正在提交的 schedule_id
  const [notice, setNotice] = useState('')

  useEffect(() => {
    fetchDepartments()
      .then((d: { departments: { name: string }[] }) => {
        const names = d.departments.map((x) => x.name)
        setDepartments(names)
        if (names.length > 0) setDept(names[0])
      })
      .catch(() => setError('科室列表加载失败'))
  }, [])

  const load = useCallback(async () => {
    if (!dept) return
    setLoading(true)
    setError('')
    try {
      const data = await fetchSchedules(token, dept, 7)
      setItems(data.schedules)
    } catch {
      setError('排班加载失败，请刷新重试')
    } finally {
      setLoading(false)
    }
  }, [token, dept])

  useEffect(() => {
    load()
  }, [load])

  // 7 天表头
  const days: string[] = (() => {
    const out: string[] = []
    const now = new Date()
    for (let i = 0; i < 7; i++) {
      const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + i)
      const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
        d.getDate(),
      ).padStart(2, '0')}`
      out.push(iso)
    }
    return out
  })()
  const todayIso = days[0]
  const tomorrowIso = days[1] ?? ''

  // 按医生分组
  const groups: DoctorGroup[] = (() => {
    const map = new Map<number, DoctorGroup>()
    for (const it of items) {
      let g = map.get(it.doctor_id)
      if (!g) {
        g = {
          doctorId: it.doctor_id,
          doctorName: it.doctor_name,
          doctorTitle: it.doctor_title ?? '',
          days: new Map(),
        }
        map.set(it.doctor_id, g)
      }
      const list = g.days.get(it.schedule_date) ?? []
      list.push(it)
      g.days.set(it.schedule_date, list)
    }
    return [...map.values()]
  })()

  const pick = useCallback(
    async (s: ScheduleItem) => {
      if (picking !== null) return
      setPicking(s.schedule_id)
      setNotice('')
      try {
        if (rescheduleId) {
          const r = await rescheduleAppointment(token, rescheduleId, s.schedule_id)
          onRescheduled?.(
            `${r.schedule.date} ${r.schedule.time} ${r.schedule.department} ${r.schedule.doctor}`,
          )
          return
        }
        const res = await selectSlot(s.schedule_id, threadId, token)
        onSelected(
          res.thread_id,
          `${res.selected.date} ${res.selected.time} ${res.selected.department} ${res.selected.doctor}`,
        )
      } catch (e) {
        setNotice(e instanceof Error ? e.message : '操作失败，请重试')
        setPicking(null)
        load() // 号源可能已变，刷新
      }
    },
    [picking, threadId, token, onSelected, onRescheduled, rescheduleId, load],
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4">
      <div className="flex max-h-[88vh] w-full max-w-3xl flex-col rounded-sm border-2 border-dai/50 bg-paper shadow-[6px_6px_0_rgba(28,26,22,0.25)]">
        {/* 头 */}
        <div className="flex items-center justify-between border-b border-thread px-6 py-4">
          <div>
            <h2 className="font-serif-sc text-lg font-black tracking-[0.2em] text-dai-deep">
              {rescheduleId ? '改约 · 选择新时段' : '门诊排班表'}
            </h2>
            <p className="mt-0.5 font-mono-id text-[10px] uppercase tracking-[0.25em] text-ink-faint">
              Available Slots · Next 7 Days · 已过期号源不显示
            </p>
          </div>
          <button
            onClick={onClose}
            className="cursor-pointer rounded-sm border border-thread px-3 py-1 font-serif-sc text-xs tracking-[0.25em] text-ink-faint transition-colors hover:border-seal hover:text-seal"
          >
            关闭
          </button>
        </div>

        {/* 科室 chips */}
        <div className="flex flex-wrap gap-2 border-b border-dashed border-thread px-6 py-3">
          {departments.map((name) => (
            <button
              key={name}
              onClick={() => setDept(name)}
              className={`cursor-pointer rounded-sm border px-3 py-1.5 font-serif-sc text-xs tracking-[0.2em] transition-colors ${
                dept === name
                  ? 'border-dai bg-dai-mist font-bold text-dai-deep'
                  : 'border-thread text-ink-soft hover:border-dai'
              }`}
            >
              {name}
            </button>
          ))}
          <button
            onClick={load}
            title="刷新"
            className="ml-auto cursor-pointer font-mono-id text-[11px] text-dai hover:text-dai-deep"
          >
            {loading ? '加载中…' : '↻ 刷新'}
          </button>
        </div>

        {/* 表体 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
          {error && <p className="py-6 text-center text-xs text-seal">{error}</p>}
          {!error && !loading && groups.length === 0 && (
            <p className="py-10 text-center text-xs leading-relaxed text-ink-faint">
              该科室近 7 天暂无可约号源
              <br />
              <span className="text-[11px] opacity-70">可换个科室看看，或直接在对话里描述症状</span>
            </p>
          )}
          {notice && <p className="mb-2 text-center text-xs text-seal">{notice}</p>}

          <div className="space-y-3">
            {groups.map((g) => (
              <div
                key={g.doctorId}
                className="rounded-sm border border-thread/70 bg-paper-deep/30 px-4 py-3"
              >
                <div className="mb-2 flex items-baseline gap-2">
                  <span className="font-serif-sc text-[14px] font-bold text-ink">
                    {g.doctorName}
                  </span>
                  {g.doctorTitle && (
                    <span className="font-serif-sc text-[11px] text-ink-faint">{g.doctorTitle}</span>
                  )}
                  <span className="font-mono-id text-[10px] text-ink-faint/70">{dept}</span>
                </div>
                <div className="grid grid-cols-7 gap-1.5">
                  {days.map((d) => {
                    const slots = g.days.get(d) ?? []
                    return (
                      <div key={d} className="min-w-0">
                        <p
                          className={`mb-1 text-center font-mono-id text-[9.5px] ${
                            d === todayIso ? 'font-bold text-dai-deep' : 'text-ink-faint'
                          }`}
                        >
                          {dayLabel(d, todayIso, tomorrowIso)}
                        </p>
                        <div className="space-y-1">
                          {slots.length === 0 && (
                            <div className="rounded-sm border border-dashed border-thread/50 py-1 text-center font-serif-sc text-[10px] text-ink-faint/40">
                              —
                            </div>
                          )}
                          {slots.map((s) => (
                            <button
                              key={s.schedule_id}
                              disabled={picking !== null}
                              onClick={() => pick(s)}
                              className={`w-full cursor-pointer rounded-sm border px-1 py-1 text-center transition-all active:scale-95 disabled:cursor-wait disabled:opacity-60 ${
                                picking === s.schedule_id
                                  ? 'border-dai bg-dai text-paper'
                                  : 'border-dai/50 bg-dai-mist/60 hover:border-dai hover:bg-dai-mist'
                              }`}
                              title={`剩 ${s.remaining} 个号源 · ${s.start_time}-${s.end_time}`}
                            >
                              <span className="block font-serif-sc text-[10.5px] font-bold text-ink">
                                {SLOT_LABEL[s.time_slot] ?? s.time_slot}
                              </span>
                              <span className="block font-mono-id text-[9px] text-ink-soft">
                                剩{s.remaining}
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 脚注 */}
        <div className="border-t border-thread px-6 py-2.5">
          <p className="font-mono-id text-[9.5px] tracking-wider text-ink-faint/70">
            点选时段后请在对话中确认 → 提交人工审批（HITL）后落库 · 号源实时校验，过期时段不可约
          </p>
        </div>
      </div>
    </div>
  )
}
