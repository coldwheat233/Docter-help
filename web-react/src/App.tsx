/** 主界面：病历纸聊天区 + 输入栏 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { sendApproval, streamChat, uploadDocument } from './api'
import AdminConsole from './components/AdminConsole'
import ApprovalCard from './components/ApprovalCard'
import LoginView from './components/LoginView'
import MessageBubble from './components/MessageBubble'
import ProgressTrail from './components/ProgressTrail'
import SchedulePanel from './components/SchedulePanel'
import Sidebar from './components/Sidebar'
import type { Appointment, ApprovalPayload, ChatMessage, Session } from './types'

const SESSION_KEY = 'medical_session'

function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    return raw ? (JSON.parse(raw) as Session) : null
  } catch {
    return null
  }
}

const WELCOME: ChatMessage = {
  role: 'assistant',
  agent: 'supervisor',
  content:
    '您好，这里是云枢医院智能预约台。\n\n直接描述您哪里不舒服就行，比如：\n· 「我最近胃疼，想挂个消化科的号」\n· 「我有什么预约？」\n\n急诊请直接拨 120。',
}

export default function App() {
  const [session, setSession] = useState<Session | null>(loadSession)
  const [threadId, setThreadId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [pendingApproval, setPendingApproval] = useState<ApprovalPayload | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [progress, setProgress] = useState<string[]>([])
  const [showSchedule, setShowSchedule] = useState(false)
  const [rescheduleTarget, setRescheduleTarget] = useState<Appointment | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const openSchedulePanel = useCallback(
    (target: Appointment | null) => {
      setRescheduleTarget(target)
      setShowSchedule(true)
    },
    [],
  )

  const handleUpload = useCallback(
    async (file: File) => {
      if (!session || uploading) return
      setUploading(true)
      setProgress(['📎 正在识别资料…'])
      try {
        const r = await uploadDocument(session.token, file, threadId)
        const lines = [`📎 已识别${r.doc_type}：《${r.title || file.name}》`]
        if (r.summary) lines.push(r.summary)
        if (r.symptoms) lines.push(`主诉：${r.symptoms}`)
        if (r.key_fields?.length) {
          lines.push(
            r.key_fields.map((f) => `${f.name} ${f.value}${f.abnormal ? ' ⚠️' : ''}`).join('；'),
          )
        }
        if (r.suggested_department) lines.push(`建议科室：${r.suggested_department}`)
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', agent: 'document_agent', content: lines.join('\n') },
        ])
        setRefreshKey((k) => k + 1) // 刷新侧边栏病历资料
      } catch (e) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            agent: 'document_agent',
            content: `❌ 上传失败：${e instanceof Error ? e.message : e}`,
          },
        ])
      } finally {
        setUploading(false)
        setTimeout(() => setProgress([]), 600)
      }
    },
    [session, uploading, threadId],
  )

  const handleLogin = useCallback((s: Session) => {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(s))
    setSession(s)
    setThreadId(null)
    setMessages([WELCOME])
    setPendingApproval(null)
  }, [])

  const handleLogout = useCallback(() => {
    sessionStorage.removeItem(SESSION_KEY)
    setSession(null)
    setThreadId(null)
    setMessages([WELCOME])
    setPendingApproval(null)
    setInput('')
  }, [])

  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, pendingApproval, busy, progress])

  const sendText = useCallback(
    async (text: string, threadOverride?: string | null) => {
      if (!text || busy || !session) return
      setBusy(true)
      setProgress([])
      setMessages((prev) => [...prev, { role: 'user', content: text }])
      await streamChat(text, threadOverride ?? threadId, session.token, {
        onProgress: (label) => setProgress((prev) => [...prev, label]),
        onMessages: (msgs) => {
          setMessages((prev) => [...prev, ...msgs.filter((m) => m.role !== 'user')])
          if (
            msgs.some(
              (m) =>
                m.role === 'tool_result' ||
                (m.agent === 'confirmer_agent' && String(m.content).includes('预约成功')),
            )
          ) {
            setRefreshKey((k) => k + 1) // 有写操作结果 → 刷新预约列表
          }
        },
        onPendingApproval: (payload) => setPendingApproval(payload),
        onDone: (tid) => {
          setThreadId(tid)
          setBusy(false)
          // 进度条停一拍再撤，让用户看到"做完了"
          setTimeout(() => setProgress([]), 900)
        },
        onError: (detail) => {
          setMessages((prev) => [...prev, { role: 'assistant', content: `❌ 请求失败：${detail}` }])
          setBusy(false)
          setProgress([])
          if (detail.includes('登录')) handleLogout() // token 失效 → 回登录页
        },
      })
    },
    [busy, threadId, session, handleLogout],
  )

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text) return
    setInput('')
    await sendText(text)
  }, [input, sendText])

  // 排班面板选号成功：接管 thread_id，自动发确认消息进入 HITL 审批
  const handleSlotSelected = useCallback(
    (newThreadId: string, summary: string) => {
      setShowSchedule(false)
      setThreadId(newThreadId)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          agent: 'scheduler_agent',
          content: `已为您锁定时段：${summary}。\n请在下方点击发送确认消息，确认后将提交人工审批。`,
        },
      ])
      // busy 时退化为填入输入框，让用户自己点发送
      if (busy) {
        setInput('好的，确认预约')
        return
      }
      // 必须显式传选号返回的 thread_id：state 闭包里的 threadId 还是旧值
      setTimeout(() => void sendText('好的，确认预约', newThreadId), 300)
    },
    [busy, sendText],
  )

  // 改约成功
  const handleRescheduled = useCallback(
    (summary: string) => {
      setShowSchedule(false)
      setRescheduleTarget(null)
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          agent: 'confirmer_agent',
          content: `✅ 改约成功！新时段：${summary}`,
        },
      ])
      setRefreshKey((k) => k + 1)
    },
    [],
  )

  const handleApprove = useCallback(
    async (decision: string) => {
      if (!threadId || busy) return
      setBusy(true)
      setPendingApproval(null) // 立即停掉"等待中台审批"轮询，防止与本次自主审批竞态
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

  // 实时感知中台审批结果：有挂起审批时轮询线程状态，
  // 中台核准/驳回后自动渲染结果消息并刷新预约列表（方案 B 患者侧）
  useEffect(() => {
    if (!pendingApproval || !threadId || !session) return
    let stopped = false
    const timer = setInterval(async () => {
      try {
        const res = await fetch(
          `/api/threads/${threadId}/status?token=${encodeURIComponent(session.token)}`,
        )
        if (!res.ok || stopped) return
        const data = await res.json()
        if (stopped || data.pending_approval) return
        // 中台已处理：以服务端线程真相为准渲染结果
        setPendingApproval(null)
        setBusy(false)
        setProgress([])
        if (Array.isArray(data.messages)) {
          setMessages((prev) => [prev[0], ...data.messages])
        }
        setRefreshKey((k) => k + 1)
      } catch {
        /* 网络抖动忽略，下一轮再试 */
      }
    }, 3000)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [pendingApproval, threadId, session])

  return (
    <div className="flex h-full">
      {!session ? (
        <div className="relative h-full w-full">
          <LoginView onLogin={handleLogin} />
        </div>
      ) : session.role === 'staff' ? (
        // 业务中台视角：工作人员登录后进入运营控制台
        <div className="h-full w-full">
          <AdminConsole token={session.token} staffName={session.name} onLogout={handleLogout} />
        </div>
      ) : (
        <>
          <Sidebar
            token={session.token}
            patientId={session.patientId}
            patientName={session.name}
            onLogout={handleLogout}
            refreshKey={refreshKey}
            onReschedule={(a) => openSchedulePanel(a)}
          />

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
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSchedule(true)}
              disabled={busy || !!pendingApproval}
              className="cursor-pointer rounded-sm border border-dai/60 px-3 py-1.5 font-serif-sc text-xs font-bold tracking-[0.2em] text-dai-deep transition-colors hover:bg-dai-mist disabled:cursor-not-allowed disabled:opacity-40"
            >
              ▤ 排班表
            </button>
            <div className="flex items-center gap-2 font-mono-id text-[10px] text-ink-faint">
              <span className="inline-block h-1.5 w-1.5 rounded-full bg-dai" />
              {busy ? 'PROCESSING' : 'READY'}
            </div>
          </div>
        </header>

        {/* 消息流 */}
        <div ref={scrollRef} className="ruled-paper min-h-0 flex-1 overflow-y-auto px-16 py-6">
          <div className="mx-auto max-w-2xl space-y-4">
            {messages.map((m, i) => (
              <MessageBubble key={i} msg={m} index={i} />
            ))}

            {busy && !pendingApproval && progress.length === 0 && (
              <div className="msg-in flex justify-start">
                <div className="flex items-center gap-1.5 rounded-sm border border-thread/70 bg-paper-deep/50 px-4 py-3">
                  <span className="think-dot h-1.5 w-1.5 rounded-full bg-dai" />
                  <span className="think-dot h-1.5 w-1.5 rounded-full bg-dai" />
                  <span className="think-dot h-1.5 w-1.5 rounded-full bg-dai" />
                </div>
              </div>
            )}

            {progress.length > 0 && !pendingApproval && <ProgressTrail steps={progress} />}

            {pendingApproval && (
              <ApprovalCard payload={pendingApproval} onDecide={handleApprove} busy={busy} />
            )}
          </div>
        </div>

        {/* 排班面板（患者直选号源 / 改约） */}
        {showSchedule && session && (
          <SchedulePanel
            token={session.token}
            threadId={threadId}
            rescheduleId={rescheduleTarget?.appointment_id ?? null}
            onClose={() => {
              setShowSchedule(false)
              setRescheduleTarget(null)
            }}
            onSelected={handleSlotSelected}
            onRescheduled={handleRescheduled}
          />
        )}

        {/* 输入栏 */}
        <footer className="border-t border-thread bg-paper px-16 py-4">
          <div className="mx-auto flex max-w-2xl items-end gap-3">
            {/* 上传检查报告/病历照片 */}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) void handleUpload(f)
                e.target.value = '' // 允许连续上传同一文件
              }}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={busy || uploading || !!pendingApproval}
              title="上传检查报告/病历照片（jpg/png/webp ≤5MB）"
              className="cursor-pointer rounded-sm border border-thread px-3 py-2.5 font-serif-sc text-sm text-ink-faint transition-colors hover:border-dai hover:text-dai-deep disabled:cursor-not-allowed disabled:opacity-40"
            >
              {uploading ? '…' : '📎'}
            </button>
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
            本系统不提供医学诊断，仅辅助预约挂号 · 所有写操作需人工审批（HITL）后落库 · 资料识别由
            GLM-4V 完成，隐私信息自动打码
          </p>
        </footer>
      </main>
        </>
      )}
    </div>
  )
}
