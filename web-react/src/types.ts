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
  /** 后端计算：是否即将就诊（未过期且 pending/confirmed） */
  is_upcoming?: boolean
  /** 后端计算：就诊时间是否已过 */
  is_past?: boolean
  symptoms?: string
  schedule_date?: string
  time_slot?: string
  start_time?: string
  end_time?: string
  doctor_name?: string
  doctor_title?: string
  department?: string
  cancelled_at?: string
  cancelled_reason?: string
  [k: string]: unknown
}

/** 排班面板：可约时段（后端只返回未过期 + 有号源的） */
export interface ScheduleItem {
  schedule_id: number
  doctor_id: number
  schedule_version: number
  doctor_name: string
  doctor_title?: string
  department: string
  schedule_date: string
  time_slot: 'morning' | 'afternoon' | 'evening'
  start_time: string
  end_time: string
  remaining: number
  capacity: number
}

/** 登录会话 */
export interface Session {
  token: string
  patientId: string
  name: string
  role?: 'patient' | 'staff'
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
  document_agent: '病历资料',
}
