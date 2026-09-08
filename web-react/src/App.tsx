/** 主界面：病历纸聊天区 + 输入栏 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { sendApproval, sendChat } from './api'
import ApprovalCard from './components/ApprovalCard'
import MessageBubble from './components/MessageBubble'
import Sidebar from './components/Sidebar'
import type { ApprovalPayload, ChatMessage } from './types'

const WELCOME: ChatMessage = {
  role: 'assistant',
  agent: 'supervisor',
  content:
    '您好，这里是云枢医院智能预约台。\n\n直接描述您哪里不舒服就行，比如：\n· 「我最近胃疼，想挂个消化科的号」\n· 「我有什么预约？」\n\n急诊请直接拨 120。',
}

export default function App() {
  // 单用户演示：固定就诊人（真实系统来自登录态，不在对话/界面上切换）
  const [patientId] = useState('P20240001')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [pendingApproval, setPendingApproval] = useState<ApprovalPayload | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, pendingApproval, busy])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setBusy(true)
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    try {
      const res = await sendChat(text, threadId, patientId)
      setThreadId(res.thread_id)
      // 后端已回传 user 消息，这里只追加非 user 的新消息
      setMessages((prev) => [...prev, ...res.messages.filter((m) => m.role !== 'user')])
      setPendingApproval(res.pending_approval)
      if (res.messages.some((m) => m.role === 'tool_result')) {
        setRefreshKey((k) => k + 1) // 有写操作结果 → 刷新预约列表
      }
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `❌ 请求失败：${e instanceof Error ? e.message : e}` },
      ])
    } finally {
      setBusy(false)
    }
  }, [input, busy, threadId, patientId])

  const handleApprove = useCallback(
    async (decision: string) => {
      if (!threadId || busy) return
      setBusy(true)
      try {
        const res = await sendApproval(threadId, decision)
        setPendingApproval(res.pending_approval)
        // 等印章动画演完再落消息
        setTimeout(() => {
          setMessages((prev) => [...prev, ...res.messages.filter((m) => m.role !== 'user')])
          setRefreshKey((k) => k + 1)
          setBusy(false)
        }, 650)
      } catch (e) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `❌ 审批提交失败：${e instanceof Error ? e.message : e}` },
        ])
        setBusy(false)
      }
    },
    [threadId, busy],
  )

  return (
    <div className="flex h-full">
      <Sidebar patientId={patientId} refreshKey={refreshKey} />

      {/* 主区：病历纸 */}
      <main className="relative flex min-w-0 flex-1 flex-col">
        {/* 装订线 */}
        <div className="pointer-events-none absolute inset-y-0 left-6 z-10 w-px bg-seal/25" />
        <div className="pointer-events-none absolute inset-y-0 left-8 z-10 w-px bg-seal/15" />

        {/* 顶栏 */}
        <header className="flex items-center justify-between border-b border-thread py-3 pl-16 pr-6">
          <div>
            <h2 className="font-serif-sc text-base font-bold tracking-wider text-ink">
              智能分诊 · 预约对话
            </h2>
            <p className="font-mono-id text-[10px] tracking-wider text-ink-faint">
              {threadId ? `THREAD ${threadId}` : 'NEW CONSULTATION'}
            </p>
          </div>
          <div className="flex items-center gap-2 font-mono-id text-[10px] text-ink-faint">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-dai" />
            {busy ? 'PROCESSING' : 'READY'}
          </div>
        </header>

        {/* 消息流 */}
        <div ref={scrollRef} className="ruled-paper min-h-0 flex-1 overflow-y-auto px-16 py-6">
          <div className="mx-auto max-w-2xl space-y-4">
            {messages.map((m, i) => (
              <MessageBubble key={i} msg={m} index={i} />
            ))}

            {busy && !pendingApproval && (
              <div className="msg-in flex justify-start">
                <div className="flex items-center gap-1.5 rounded-sm border border-thread/70 bg-paper-deep/50 px-4 py-3">
                  <span className="think-dot h-1.5 w-1.5 rounded-full bg-dai" />
                  <span className="think-dot h-1.5 w-1.5 rounded-full bg-dai" />
                  <span className="think-dot h-1.5 w-1.5 rounded-full bg-dai" />
                </div>
              </div>
            )}

            {pendingApproval && (
              <ApprovalCard payload={pendingApproval} onDecide={handleApprove} busy={busy} />
            )}
          </div>
        </div>

        {/* 输入栏 */}
        <footer className="border-t border-thread bg-paper px-16 py-4">
          <div className="mx-auto flex max-w-2xl items-end gap-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              disabled={busy || !!pendingApproval}
              placeholder={
                pendingApproval ? '请先处理上方审批单…' : '描述您哪里不舒服…（Enter 发送）'
              }
              rows={2}
              className="min-w-0 flex-1 resize-none rounded-sm border border-thread bg-paper-deep/30 px-4 py-2.5 text-[14px] leading-relaxed text-ink outline-none transition-colors placeholder:text-ink-faint/60 focus:border-dai disabled:opacity-50"
            />
            <button
              onClick={handleSend}
              disabled={busy || !!pendingApproval || !input.trim()}
              className="cursor-pointer rounded-sm border-2 border-dai px-5 py-2.5 font-serif-sc text-sm font-bold tracking-[0.25em] text-dai transition-all hover:bg-dai hover:text-paper active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              发送
            </button>
          </div>
          <p className="mx-auto mt-2 max-w-2xl font-mono-id text-[9.5px] tracking-wider text-ink-faint/60">
            本系统不提供医学诊断，仅辅助预约挂号 · 所有写操作需人工审批（HITL）后落库
          </p>
        </footer>
      </main>
    </div>
  )
}
