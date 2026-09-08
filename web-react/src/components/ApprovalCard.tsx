/** HITL 审批卡片：病历审批单 + 盖章动画 */

import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import type { ApprovalPayload } from '../types'

interface Props {
  payload: ApprovalPayload
  onDecide: (decision: string) => void
  busy: boolean
}

const FIELD_LABELS: [string, string][] = [
  ['patient_id', '患者编号'],
  ['schedule_date', '就诊日期'],
  ['time_slot', '时段'],
  ['symptoms', '主诉'],
  ['duration', '病程'],
  ['severity', '严重程度'],
  ['reason', '原因'],
]

const SEVERITY_LABELS: Record<string, string> = {
  mild: '轻微',
  moderate: '中等',
  severe: '严重',
}

const TIME_SLOT_LABELS: Record<string, string> = {
  morning: '上午 08:00–12:00',
  afternoon: '下午 14:00–18:00',
  evening: '晚间 18:30–21:00',
}

export default function ApprovalCard({ payload, onDecide, busy }: Props) {
  const [rejectReason, setRejectReason] = useState('')
  const [decided, setDecided] = useState<'approve' | 'reject' | null>(null)

  const handle = (decision: 'approve' | 'reject') => {
    setDecided(decision)
    onDecide(decision === 'approve' ? 'approve' : `reject:${rejectReason || '审核员未填写原因'}`)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 14, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      className="approval-glow relative mx-auto my-3 w-full max-w-lg overflow-hidden rounded-sm border-2 bg-paper-deep/60 p-0 shadow-[0_8px_30px_-12px_rgba(28,26,22,0.35)]"
    >
      {/* 审批单抬头 */}
      <div className="flex items-center justify-between border-b border-dashed border-ink-faint/40 px-5 py-2.5">
        <span className="font-serif-sc text-sm font-bold tracking-[0.3em] text-seal">
          人工审批单
        </span>
        <span className="font-mono-id text-[10px] tracking-wider text-ink-faint">
          HITL·{payload.type ?? 'WRITE'}
        </span>
      </div>

      <div className="px-5 py-4">
        <p className="mb-3 font-serif-sc text-base font-semibold text-ink">
          {payload.action ?? '待审批操作'}
        </p>

        <dl className="space-y-1.5">
          {FIELD_LABELS.map(([key, label]) => {
            const raw = payload[key]
            if (raw === undefined || raw === null || raw === '') return null
            let text = String(raw)
            if (key === 'severity') text = SEVERITY_LABELS[text] ?? text
            if (key === 'time_slot') text = TIME_SLOT_LABELS[text] ?? text
            return (
              <div key={key} className="flex items-baseline gap-3 text-[13px]">
                <dt className="w-16 shrink-0 text-right font-serif-sc text-ink-faint">{label}</dt>
                <dd className="font-mono-id text-ink-soft">{text}</dd>
              </div>
            )
          })}
        </dl>

        {/* 操作区 / 印章 */}
        <div className="relative mt-4 min-h-16">
          <AnimatePresence mode="wait">
            {decided === null && (
              <motion.div key="btns" exit={{ opacity: 0 }} className="space-y-2.5">
                <div className="flex gap-2.5">
                  <button
                    onClick={() => handle('approve')}
                    disabled={busy}
                    className="flex-1 cursor-pointer rounded-sm bg-seal px-4 py-2 font-serif-sc text-sm font-bold tracking-widest text-paper shadow-[0_3px_0_var(--color-seal-deep)] transition-all hover:bg-seal-deep active:translate-y-0.5 active:shadow-none disabled:opacity-50"
                  >
                    核准执行
                  </button>
                  <button
                    onClick={() => handle('reject')}
                    disabled={busy}
                    className="flex-1 cursor-pointer rounded-sm border border-ink-faint/50 bg-transparent px-4 py-2 font-serif-sc text-sm tracking-widest text-ink-soft transition-colors hover:border-seal hover:text-seal disabled:opacity-50"
                  >
                    驳回
                  </button>
                </div>
                <input
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="驳回原因（可选）"
                  className="w-full rounded-sm border border-thread bg-paper px-3 py-1.5 text-xs text-ink-soft outline-none placeholder:text-ink-faint/60 focus:border-seal/50"
                />
              </motion.div>
            )}

            {decided === 'approve' && (
              <motion.div key="stamp" className="pointer-events-none absolute -top-2 right-1">
                <div className="stamp-in seal-texture flex h-20 w-20 items-center justify-center rounded-full border-[3px] border-seal bg-seal/[0.06]">
                  <div className="flex h-16 w-16 items-center justify-center rounded-full border border-seal/70">
                    <span className="font-serif-sc text-lg font-black tracking-[0.15em] text-seal">
                      已核准
                    </span>
                  </div>
                </div>
              </motion.div>
            )}

            {decided === 'reject' && (
              <motion.div key="reject" className="pointer-events-none absolute -top-2 right-1">
                <div className="stamp-in seal-texture flex h-20 w-20 items-center justify-center rounded-sm border-[3px] border-ink-soft/70 bg-ink/[0.03]">
                  <span className="font-serif-sc text-lg font-black tracking-[0.15em] text-ink-soft">
                    已驳回
                  </span>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {decided !== null && (
            <p className="pt-2 text-xs text-ink-faint">
              {busy ? '系统执行中…' : '已提交审批结果'}
            </p>
          )}
        </div>
      </div>

      {/* 底部齿孔 */}
      <div
        className="h-2.5 w-full"
        style={{
          backgroundImage:
            'radial-gradient(circle at 6px 5px, var(--color-paper) 3px, transparent 3.5px)',
          backgroundSize: '14px 10px',
          backgroundColor: 'var(--color-paper-deep)',
        }}
      />
    </motion.div>
  )
}
