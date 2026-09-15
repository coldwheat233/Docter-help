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
// 排班可视化（患者直选）
// =====================================================================
export async function fetchSchedules(token: string, department: string | null, days = 7) {
  const params = new URLSearchParams({ token, days: String(days) })
  if (department) params.set('department', department)
  const res = await fetch(`/api/schedules?${params.toString()}`)
  if (!res.ok) throw new Error(`schedules → ${res.status}`)
  return res.json() as Promise<{
    days: number
    count: number
    schedules: import('./types').ScheduleItem[]
  }>
}

export function selectSlot(scheduleId: number, threadId: string | null, token: string) {
  return post('/api/select-slot', {
    schedule_id: scheduleId,
    thread_id: threadId,
    token,
  }) as Promise<{
    success: boolean
    thread_id: string
    selected: { date: string; time: string; department: string; doctor: string }
    next: string
  }>
}

// =====================================================================
// 业务中台（staff）
// =====================================================================
async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
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

export interface ApprovalItem {
  thread_id: string
  type: string
  action: string
  patient_id: string
  patient_name: string
  patient_phone?: string
  schedule_date?: string
  time_slot?: string
  doctor_id?: number
  symptoms?: string
  duration?: string
  severity?: string
  ask?: string
}

export const adminApi = {
  approvals: (token: string) =>
    get<{ count: number; approvals: ApprovalItem[] }>(
      `/api/admin/approvals?token=${encodeURIComponent(token)}`,
    ),
  decide: (token: string, threadId: string, decision: string) =>
    post(
      `/api/admin/approvals/decision?token=${encodeURIComponent(token)}`,
      { thread_id: threadId, decision },
    ) as Promise<{ success: boolean; messages: unknown[] }>,
  stats: (token: string) =>
    get<Record<string, number>>(`/api/admin/stats?token=${encodeURIComponent(token)}`),
  audit: (token: string, limit = 30) =>
    get<{ audit: Record<string, unknown>[] }>(
      `/api/admin/audit?token=${encodeURIComponent(token)}&limit=${limit}`,
    ),
  createSchedule: (token: string, body: { doctor_id: number; schedule_date: string; time_slot: string; capacity: number }) =>
    post(`/api/admin/schedules?token=${encodeURIComponent(token)}`, body) as Promise<{ success: boolean; schedule_id?: number; error_message?: string }>,
  scheduleOp: (token: string, scheduleId: number, op: 'cancel' | 'restore' | 'capacity', body: { reason?: string; new_capacity?: number }) =>
    post(`/api/admin/schedules/${scheduleId}/${op}?token=${encodeURIComponent(token)}`, body) as Promise<{ success: boolean; error_message?: string }>,
  createDoctor: (token: string, body: { name: string; department: string; title: string; specialty: string }) =>
    post(`/api/admin/doctors?token=${encodeURIComponent(token)}`, body) as Promise<{ success: boolean; doctor_id?: number; error_message?: string }>,
}

// =====================================================================
// 多模态 + 就诊摘要 + 直操（患者侧，v6）
// =====================================================================
export interface PatientDocument {
  id: number
  doc_type: string
  title: string
  summary: string
  urgent: boolean
  created_at: string
}

export async function fetchDocuments(token: string) {
  return get<{ count: number; documents: PatientDocument[] }>(
    `/api/documents?token=${encodeURIComponent(token)}`,
  )
}

export async function uploadDocument(
  token: string,
  file: File,
  threadId: string | null,
): Promise<{ success: boolean; document_id: number; doc_type: string; title: string; summary: string; symptoms: string; key_fields: { name: string; value: string; abnormal: boolean }[]; suggested_department: string; urgent: boolean }> {
  const form = new FormData()
  form.append('file', file)
  const params = new URLSearchParams({ token })
  if (threadId) params.set('thread_id', threadId)
  const res = await fetch(`/api/upload?${params.toString()}`, { method: 'POST', body: form })
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

export function fetchSummary(token: string, refresh = false) {
  return get<{ summary: string; cached?: boolean; empty?: boolean }>(
    `/api/summary?token=${encodeURIComponent(token)}${refresh ? '&refresh=1' : ''}`,
  )
}

export function cancelAppointment(token: string, appointmentId: string, reason: string) {
  return post(
    `/api/appointments/${appointmentId}/cancel?token=${encodeURIComponent(token)}`,
    { reason },
  ) as Promise<{ success: boolean }>
}

export function rescheduleAppointment(token: string, appointmentId: string, newScheduleId: number) {
  return post(
    `/api/appointments/${appointmentId}/reschedule?token=${encodeURIComponent(token)}`,
    { new_schedule_id: newScheduleId },
  ) as Promise<{
    success: boolean
    schedule: { date: string; time: string; department: string; doctor: string }
  }>
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
