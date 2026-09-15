/** 业务中台（staff 视角）：审批队列 / 今日概览 / 排班管理 / 审计日志 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { adminApi, type ApprovalItem } from '../api'

interface Props {
  token: string
  staffName: string
  onLogout: () => void
}

type Tab = 'approvals' | 'stats' | 'schedules' | 'audit'

const TAB_LABELS: Record<Tab, string> = {
  approvals: '待审批',
  stats: '今日概览',
  schedules: '排班管理',
  audit: '审计日志',
}

const SLOT_LABEL: Record<string, string> = { morning: '上午', afternoon: '下午', evening: '晚班' }

const SEVERITY_LABEL: Record<string, string> = { mild: '轻微', moderate: '中度', severe: '剧烈' }

function StatsCard({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="rounded-sm border border-thread bg-paper px-4 py-3">
      <p className="font-mono-id text-[10px] uppercase tracking-[0.2em] text-ink-faint">{label}</p>
      <p className="mt-1 font-serif-sc text-2xl font-black text-ink">{value}</p>
    </div>
  )
}

function ApprovalCardView({
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
    <div className="rounded-sm border border-thread bg-paper px-4 py-3 shadow-[2px_2px_0_rgba(28,26,22,0.06)]">
      <div className="flex items-center justify-between">
        <span className="font-serif-sc text-[14px] font-bold text-ink">
          {item.patient_name}
          {item.patient_phone ? <span className="ml-2 font-mono-id text-[10px] text-ink-faint">{item.patient_phone}</span> : null}
        </span>
        <span className="rounded-sm bg-paper-deep px-1.5 py-0.5 font-mono-id text-[9.5px] tracking-wider text-ink-soft">
          {item.type}
        </span>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px] text-ink-soft">
        {item.schedule_date && (
          <p>
            就诊：<span className="font-bold text-ink">{item.schedule_date}</span>
          </p>
        )}
        {item.time_slot && (
          <p>
            时段：<span className="font-bold text-ink">{SLOT_LABEL[item.time_slot] ?? item.time_slot}</span>
          </p>
        )}
        {item.symptoms && (
          <p className="col-span-2">
            主诉：{item.symptoms}
            {item.severity ? `（${SEVERITY_LABEL[item.severity] ?? item.severity}）` : ''}
          </p>
        )}
        <p className="col-span-2 font-mono-id text-[10px] text-ink-faint">
          thread {item.thread_id}
        </p>
      </div>
      <div className="mt-2.5 flex items-center gap-2">
        {!rejecting ? (
          <>
            <button
              disabled={busy}
              onClick={() => onDecide(item.thread_id, 'approve')}
              className="cursor-pointer rounded-sm border-2 border-dai bg-dai-mist px-4 py-1.5 font-serif-sc text-xs font-bold tracking-[0.2em] text-dai-deep transition-colors hover:bg-dai hover:text-paper disabled:opacity-40"
            >
              ✓ 核准执行
            </button>
            <button
              disabled={busy}
              onClick={() => setRejecting(true)}
              className="cursor-pointer rounded-sm border border-seal/60 px-4 py-1.5 font-serif-sc text-xs tracking-[0.2em] text-seal transition-colors hover:bg-seal hover:text-paper disabled:opacity-40"
            >
              驳回
            </button>
          </>
        ) : (
          <>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="驳回原因（必填）"
              className="min-w-0 flex-1 rounded-sm border border-thread bg-paper-deep/30 px-3 py-1.5 text-xs text-ink outline-none focus:border-seal"
            />
            <button
              disabled={busy || !reason.trim()}
              onClick={() => onDecide(item.thread_id, `reject:${reason.trim()}`)}
              className="cursor-pointer rounded-sm bg-seal px-4 py-1.5 font-serif-sc text-xs font-bold tracking-[0.2em] text-paper disabled:opacity-40"
            >
              确认驳回
            </button>
            <button
              onClick={() => setRejecting(false)}
              className="cursor-pointer font-mono-id text-[10px] text-ink-faint hover:text-ink"
            >
              取消
            </button>
          </>
        )}
      </div>
    </div>
  )
}

export default function AdminConsole({ token, staffName, onLogout }: Props) {
  const [tab, setTab] = useState<Tab>('approvals')
  const [approvals, setApprovals] = useState<ApprovalItem[]>([])
  const [stats, setStats] = useState<Record<string, number>>({})
  const [audit, setAudit] = useState<Record<string, unknown>[]>([])
  const [loading, setLoading] = useState(false)
  const [busyThread, setBusyThread] = useState<string | null>(null)
  const [notice, setNotice] = useState('')

  // 排班管理表单
  const [doctorId, setDoctorId] = useState('1')
  const [scheduleDate, setScheduleDate] = useState('')
  const [slot, setSlot] = useState<'morning' | 'afternoon' | 'evening'>('morning')
  const [capacity, setCapacity] = useState('20')
  const [schedMsg, setSchedMsg] = useState('')
  const tabRef = useRef<Tab>('approvals')

  useEffect(() => {
    tabRef.current = tab
  }, [tab])

  const load = useCallback(async () => {
    setLoading(true)
    setNotice('')
    try {
      if (tab === 'approvals') {
        const d = await adminApi.approvals(token)
        setApprovals(d.approvals ?? [])
      } else if (tab === 'stats') {
        setStats(await adminApi.stats(token))
      } else if (tab === 'audit') {
        const d = await adminApi.audit(token, 30)
        setAudit(d.audit ?? [])
      }
    } catch (e) {
      setNotice(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [tab, token])

  useEffect(() => {
    load()
  }, [load])

  // 实时推送：订阅审批队列 SSE 流，患者一提交/处理完，队列秒级更新（含其他页签的角标）
  useEffect(() => {
    const es = new EventSource(`/api/admin/approvals/stream?token=${encodeURIComponent(token)}`)
    es.addEventListener('approvals', (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data)
        setApprovals(d.approvals ?? [])
        if (tabRef.current === 'approvals') setNotice('')
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
      } catch (e) {
        setNotice(e instanceof Error ? e.message : '处理失败')
      } finally {
        setBusyThread(null)
      }
    },
    [token],
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
      setSchedMsg(
        r.success ? `✅ 排班已创建（schedule_id ${r.schedule_id}）` : `❌ ${r.error_message ?? '创建失败'}`,
      )
    } catch (e) {
      setSchedMsg(`❌ ${e instanceof Error ? e.message : '创建失败'}`)
    }
  }, [token, doctorId, scheduleDate, slot, capacity])

  return (
    <div className="flex h-full flex-col bg-paper">
      {/* 顶栏 */}
      <header className="flex items-center justify-between border-b-2 border-ink/70 bg-paper-deep/40 px-6 py-3.5">
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
            onClick={onLogout}
            className="cursor-pointer rounded-sm border border-thread px-3 py-1.5 font-serif-sc text-[11px] tracking-[0.25em] text-ink-faint transition-colors hover:border-seal hover:text-seal"
          >
            退出
          </button>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-thread px-6 pt-3">
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`cursor-pointer rounded-t-sm border border-b-0 px-4 py-2 font-serif-sc text-xs tracking-[0.2em] transition-colors ${
              tab === t
                ? 'border-thread bg-paper font-bold text-dai-deep'
                : 'border-transparent text-ink-faint hover:text-ink-soft'
            }`}
          >
            {TAB_LABELS[t]}
            {t === 'approvals' && approvals.length > 0 ? ` · ${approvals.length}` : ''}
          </button>
        ))}
        <button
          onClick={load}
          className="ml-auto cursor-pointer pb-2 font-mono-id text-[11px] text-dai hover:text-dai-deep"
        >
          {loading ? '加载中…' : '↻ 刷新'}
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {notice && (
          <p className="mb-3 rounded-sm border border-dai/40 bg-dai-mist/50 px-3 py-2 text-xs text-dai-deep">
            {notice}
          </p>
        )}

        {tab === 'approvals' && (
          <div className="mx-auto max-w-2xl space-y-3">
            {approvals.length === 0 && !loading && (
              <p className="mt-10 text-center text-xs text-ink-faint">
                暂无待审批申请
                <br />
                <span className="text-[11px] opacity-70">患者提交预约确认后会实时出现在这里</span>
              </p>
            )}
            {approvals.map((a) => (
              <ApprovalCardView
                key={a.thread_id}
                item={a}
                busy={busyThread === a.thread_id}
                onDecide={decide}
              />
            ))}
          </div>
        )}

        {tab === 'stats' && (
          <div className="grid max-w-2xl grid-cols-2 gap-3 sm:grid-cols-3">
            <StatsCard label="总预约" value={stats.total_appointments ?? '-'} />
            <StatsCard label="已确认" value={stats.confirmed ?? '-'} />
            <StatsCard label="已取消" value={stats.cancelled ?? '-'} />
            <StatsCard label="已就诊" value={stats.completed ?? '-'} />
            <StatsCard label="排班数" value={stats.total_schedules ?? '-'} />
            <StatsCard label="医生数" value={stats.total_doctors ?? '-'} />
            <StatsCard label="患者数" value={stats.total_patients ?? '-'} />
          </div>
        )}

        {tab === 'schedules' && (
          <div className="max-w-xl space-y-3">
            <div className="rounded-sm border border-thread bg-paper px-4 py-3">
              <p className="mb-2 font-serif-sc text-[12px] tracking-[0.25em] text-ink-faint">新增排班</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <label className="flex flex-col gap-1">
                  <span className="text-ink-faint">医生 ID</span>
                  <input
                    value={doctorId}
                    onChange={(e) => setDoctorId(e.target.value)}
                    className="rounded-sm border border-thread bg-paper-deep/30 px-2 py-1.5 text-ink outline-none focus:border-dai"
                  />
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
            <p className="text-[11px] leading-relaxed text-ink-faint">
              停用 / 恢复 / 调整容量 / 新增医生：REST 接口已就绪（POST /api/admin/schedules/&#123;id&#125;/&#123;cancel|restore|capacity&#125;、/api/admin/doctors），界面按需接入。
            </p>
          </div>
        )}

        {tab === 'audit' && (
          <div className="max-w-3xl overflow-x-auto rounded-sm border border-thread bg-paper">
            <table className="w-full text-left text-[11.5px]">
              <thead>
                <tr className="border-b border-thread bg-paper-deep/40 font-mono-id text-[10px] uppercase tracking-wider text-ink-faint">
                  <th className="px-3 py-2">时间</th>
                  <th className="px-3 py-2">事件</th>
                  <th className="px-3 py-2">对象</th>
                  <th className="px-3 py-2">操作者</th>
                </tr>
              </thead>
              <tbody>
                {audit.map((a, i) => (
                  <tr key={i} className="border-b border-dashed border-thread/50 text-ink-soft">
                    <td className="px-3 py-1.5 font-mono-id text-[10px]">
                      {String(a.created_at ?? '').slice(0, 19)}
                    </td>
                    <td className="px-3 py-1.5">{String(a.event_type ?? '')}</td>
                    <td className="px-3 py-1.5 font-mono-id text-[10px]">
                      {String(a.entity_type ?? '')}#{String(a.entity_id ?? '')}
                    </td>
                    <td className="px-3 py-1.5">{String(a.actor ?? '')}</td>
                  </tr>
                ))}
                {audit.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-3 py-6 text-center text-ink-faint">
                      暂无审计记录
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
