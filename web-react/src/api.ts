/** API 客户端（对接 web/api.py，dev 走 vite proxy） */

import type { ApprovalPayload, ChatMessage, ChatResponse, Session } from './types'

// =====================================================================
// 认证
// =====================================================================
export function login(username: string, password: string): Promise<Session> {
  return post('/api/login', { username, password })
}

export function register(
  username: string,
  password: string,
  name: string,
  phone = '',
): Promise<Session> {
  return post('/api/register', { username, password, name, phone })
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    throw new Error(`${detail}`)
  }
  return res.json()
}

export function sendChat(message: string, threadId: string | null, token: string): Promise<ChatResponse> {
  return post('/api/chat', { message, thread_id: threadId, token })
}

export function sendApproval(threadId: string, decision: string): Promise<ChatResponse> {
  return post('/api/approve', { thread_id: threadId, decision })
}

export async function fetchAppointments(token: string) {
  const res = await fetch(`/api/appointments?token=${encodeURIComponent(token)}`)
  if (!res.ok) throw new Error(`appointments → ${res.status}`)
  return res.json()
}

export async function fetchDepartments() {
  const res = await fetch('/api/departments')
  if (!res.ok) throw new Error(`departments → ${res.status}`)
  return res.json()
}

// =====================================================================
// SSE 流式对话
// =====================================================================
export interface StreamHandlers {
  /** 进度事件（白名单话术，如"正在查询排班…"） */
  onProgress?: (label: string) => void
  /** 最终消息批次 */
  onMessages?: (messages: ChatMessage[]) => void
  /** HITL 审批点 */
  onPendingApproval?: (payload: ApprovalPayload) => void
  /** 流结束（拿到 thread_id） */
  onDone?: (threadId: string) => void
  onError?: (detail: string) => void
}

export async function streamChat(
  message: string,
  threadId: string | null,
  token: string,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId, token }),
  })
  if (!res.ok || !res.body) {
    let detail = `${res.status}`
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* ignore */
    }
    handlers.onError?.(detail)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (block: string) => {
    const lines = block.split('\n')
    let event = ''
    let data = ''
    for (const line of lines) {
      if (line.startsWith('event:')) event = line.slice(6).trim()
      else if (line.startsWith('data:')) data = line.slice(5).trim()
    }
    if (!event || !data) return
    let parsed: unknown
    try {
      parsed = JSON.parse(data)
    } catch {
      return
    }
    switch (event) {
      case 'progress':
        handlers.onProgress?.((parsed as { label: string }).label)
        break
      case 'messages':
        handlers.onMessages?.(parsed as ChatMessage[])
        break
      case 'pending_approval':
        handlers.onPendingApproval?.(parsed as ApprovalPayload)
        break
      case 'done':
        handlers.onDone?.((parsed as { thread_id: string }).thread_id)
        break
      case 'error':
        handlers.onError?.((parsed as { detail: string }).detail)
        break
    }
  }

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      dispatch(buffer.slice(0, idx))
      buffer = buffer.slice(idx + 2)
    }
  }
  if (buffer.trim()) dispatch(buffer)
}

export type { ApprovalPayload }
