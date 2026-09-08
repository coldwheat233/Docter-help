/** API 客户端（对接 web/api.py，dev 走 vite proxy） */

import type { ApprovalPayload, ChatResponse } from './types'

async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`${url} → ${res.status}`)
  return res.json()
}

export function sendChat(
  message: string,
  threadId: string | null,
  patientId: string,
): Promise<ChatResponse> {
  return post('/api/chat', { message, thread_id: threadId, patient_id: patientId })
}

export function sendApproval(threadId: string, decision: string): Promise<ChatResponse> {
  return post('/api/approve', { thread_id: threadId, decision })
}

export async function fetchAppointments(patientId: string) {
  const res = await fetch(`/api/appointments?patient_id=${encodeURIComponent(patientId)}`)
  if (!res.ok) throw new Error(`appointments → ${res.status}`)
  return res.json()
}

export async function fetchDepartments() {
  const res = await fetch('/api/departments')
  if (!res.ok) throw new Error(`departments → ${res.status}`)
  return res.json()
}

export type { ApprovalPayload }
