/** 聊天气泡：病历文书风 */

import type { ChatMessage } from '../types'
import { AGENT_LABELS } from '../types'

interface Props {
  msg: ChatMessage
  index: number
}

export default function MessageBubble({ msg, index }: Props) {
  const delay = `${Math.min(index * 40, 200)}ms`

  if (msg.role === 'user') {
    return (
      <div className="msg-in flex justify-end" style={{ animationDelay: delay }}>
        <div className="max-w-[78%] rounded-sm rounded-br-none bg-dai px-4 py-2.5 text-[14px] leading-relaxed text-paper shadow-[2px_2px_0_rgba(22,67,66,0.25)]">
          {msg.content}
        </div>
      </div>
    )
  }

  if (msg.role === 'tool_result') {
    const ok = msg.data?.success
    return (
      <div className="msg-in flex justify-center" style={{ animationDelay: delay }}>
        <div
          className={`w-full max-w-md rounded-sm border-l-[3px] px-4 py-3 font-mono-id text-[12.5px] leading-relaxed ${
            ok
              ? 'border-dai bg-dai-mist/60 text-dai-deep'
              : 'border-seal bg-seal/[0.06] text-seal-deep'
          }`}
        >
          {ok ? '✓ ' : '✗ '}
          {msg.data?.appointment_id && (
            <span className="font-semibold">预约号 {msg.data.appointment_id} · </span>
          )}
          {ok ? '操作成功' : (msg.data?.error_message ?? '操作失败')}
          {msg.data?.error_code && (
            <span className="ml-1 opacity-60">[{msg.data.error_code}]</span>
          )}
        </div>
      </div>
    )
  }

  // assistant
  const agentLabel = AGENT_LABELS[msg.agent ?? ''] ?? null
  const isEmergency = msg.agent === 'emergency'

  return (
    <div className="msg-in flex justify-start" style={{ animationDelay: delay }}>
      <div className="max-w-[82%]">
        {agentLabel && (
          <div
            className={`mb-1 flex items-center gap-1.5 font-serif-sc text-[11px] tracking-widest ${
              isEmergency ? 'text-seal' : 'text-ink-faint'
            }`}
          >
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${
                isEmergency ? 'urgent-pulse bg-seal' : 'bg-dai/60'
              }`}
            />
            {agentLabel}
          </div>
        )}
        <div
          className={`whitespace-pre-wrap rounded-sm rounded-tl-none border px-4 py-2.5 text-[14px] leading-relaxed ${
            isEmergency
              ? 'border-seal/40 bg-seal/[0.05] text-seal-deep'
              : 'border-thread/70 bg-paper-deep/50 text-ink'
          }`}
        >
          {msg.content}
        </div>
      </div>
    </div>
  )
}
