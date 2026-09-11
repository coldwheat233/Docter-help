/** 进度流转条：病历单上的"经办记录"风 */

import { AnimatePresence, motion } from 'motion/react'

interface Props {
  steps: string[]
}

export default function ProgressTrail({ steps }: Props) {
  if (steps.length === 0) return null

  return (
    <div className="msg-in flex justify-start">
      <div className="rounded-sm border border-dashed border-dai/40 bg-dai-mist/30 px-4 py-2.5">
        <p className="mb-1.5 font-serif-sc text-[10px] tracking-[0.3em] text-dai/70">经办记录</p>
        <div className="space-y-1">
          <AnimatePresence initial={false}>
            {steps.map((s, i) => {
              const isLast = i === steps.length - 1
              return (
                <motion.div
                  key={`${i}-${s}`}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  className={`flex items-center gap-2 text-[12px] ${
                    isLast ? 'text-dai-deep font-medium' : 'text-ink-faint'
                  }`}
                >
                  {isLast ? (
                    <span className="flex gap-0.5">
                      <span className="think-dot h-1 w-1 rounded-full bg-dai" />
                      <span className="think-dot h-1 w-1 rounded-full bg-dai" />
                      <span className="think-dot h-1 w-1 rounded-full bg-dai" />
                    </span>
                  ) : (
                    <span className="font-mono-id text-[10px] text-dai/60">✓</span>
                  )}
                  {s}
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}
