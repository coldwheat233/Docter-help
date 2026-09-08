/** API 类型定义（与 web/api.py 对齐） */

export interface ChatMessage {
  role: 'user' | 'assistant' | 'tool_result'
  content: string
  agent?: string
  /** tool_result 时的结构化数据（预约成功/失败） */
  data?: {
    success: boolean
    appointment_id?: string
    error_code?: string
    error_message?: string
    [k: string]: unknown
  }
}

export interface ApprovalPayload {
  type?: string
  action?: string
  patient_id?: string
  doctor_id?: number
  schedule_id?: number
  appointment_id?: string
  symptoms?: string
  duration?: string
  severity?: string
  schedule_date?: string
  time_slot?: string
  reason?: string
  ask?: string
  [k: string]: unknown
}

export interface ChatResponse {
  thread_id: string
  messages: ChatMessage[]
  pending_approval: ApprovalPayload | null
  blocked: boolean
}

export interface Appointment {
  id: string
  appointment_id?: string
  status: 'confirmed' | 'pending' | 'cancelled' | 'completed' | 'no_show'
  symptoms?: string
  schedule_date?: string
  time_slot?: string
  doctor_name?: string
  doctor_title?: string
  department?: string
  [k: string]: unknown
}

export const AGENT_LABELS: Record<string, string> = {
  router_agent: '分诊台',
  intake_agent: '问诊记录',
  scheduler_agent: '排班推荐',
  confirmer_agent: '预约确认',
  knowledge_agent: '医学知识库',
  supervisor: '调度中心',
  guardrail: '安全护栏',
  emergency: '急诊指引',
  rate_limit: '限流保护',
}
