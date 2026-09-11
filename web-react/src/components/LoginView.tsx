/** 登录/注册页：病历夹封面 */

import { useState } from 'react'
import { motion } from 'motion/react'
import { login, register } from '../api'
import type { Session } from '../types'

interface Props {
  onLogin: (s: Session) => void
}

export default function LoginView({ onLogin }: Props) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    if (busy || !username.trim() || !password) return
    if (mode === 'register' && !name.trim()) return
    setBusy(true)
    setError('')
    try {
      const session =
        mode === 'login'
          ? await login(username.trim(), password)
          : await register(username.trim(), password, name.trim(), phone.trim())
      onLogin(session)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') submit()
  }

  return (
    <div className="flex h-full items-center justify-center">
      {/* 背景装饰：大号水印印章 */}
      <div className="pointer-events-none absolute right-[12%] top-[14%] select-none font-serif-sc text-[180px] font-black leading-none text-dai/[0.05]">
        云枢
      </div>

      <motion.div
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="relative w-full max-w-sm"
      >
        {/* 病历夹封面 */}
        <div className="overflow-hidden rounded-sm border border-thread bg-paper-deep/60 shadow-[0_20px_60px_-20px_rgba(28,26,22,0.4)]">
          {/* 封面头 */}
          <div className="border-b border-dashed border-ink-faint/40 px-8 pb-5 pt-7">
            <div className="flex items-end justify-between">
              <div>
                <h1 className="font-serif-sc text-3xl font-black tracking-[0.25em] text-dai-deep">
                  云枢医院
                </h1>
                <p className="mt-1.5 font-mono-id text-[10px] uppercase tracking-[0.3em] text-ink-faint">
                  Outpatient Appointment
                </p>
              </div>
              {/* 小红章装饰 */}
              <div className="flex h-12 w-12 -rotate-12 items-center justify-center rounded-full border-2 border-seal/60">
                <span className="font-serif-sc text-[13px] font-bold text-seal/80">预约</span>
              </div>
            </div>
          </div>

          {/* 表单 */}
          <div className="space-y-4 px-8 py-6" onKeyDown={onKey}>
            {/* 模式切换 */}
            <div className="flex border-b border-thread">
              {(['login', 'register'] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    setMode(m)
                    setError('')
                  }}
                  className={`cursor-pointer px-4 pb-2 font-serif-sc text-sm tracking-widest transition-colors ${
                    mode === m
                      ? 'border-b-2 border-dai font-bold text-dai-deep'
                      : 'text-ink-faint hover:text-ink-soft'
                  }`}
                >
                  {m === 'login' ? '登 录' : '注 册'}
                </button>
              ))}
            </div>

            <label className="block">
              <span className="font-serif-sc text-[11px] tracking-[0.25em] text-ink-faint">账号</span>
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="mt-1 w-full rounded-sm border border-thread bg-paper px-3 py-2 text-sm outline-none transition-colors focus:border-dai"
                placeholder="用户名"
                autoComplete="username"
              />
            </label>

            <label className="block">
              <span className="font-serif-sc text-[11px] tracking-[0.25em] text-ink-faint">密码</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded-sm border border-thread bg-paper px-3 py-2 text-sm outline-none transition-colors focus:border-dai"
                placeholder="密码"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              />
            </label>

            {mode === 'register' && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                className="space-y-4"
              >
                <label className="block">
                  <span className="font-serif-sc text-[11px] tracking-[0.25em] text-ink-faint">
                    就诊人姓名
                  </span>
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="mt-1 w-full rounded-sm border border-thread bg-paper px-3 py-2 text-sm outline-none transition-colors focus:border-dai"
                    placeholder="真实姓名（病历用）"
                  />
                </label>
                <label className="block">
                  <span className="font-serif-sc text-[11px] tracking-[0.25em] text-ink-faint">
                    手机号（选填）
                  </span>
                  <input
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="mt-1 w-full rounded-sm border border-thread bg-paper px-3 py-2 font-mono-id text-sm outline-none transition-colors focus:border-dai"
                    placeholder="138****0000"
                  />
                </label>
              </motion.div>
            )}

            {error && (
              <p className="rounded-sm border-l-2 border-seal bg-seal/[0.06] px-3 py-2 text-xs text-seal-deep">
                {error}
              </p>
            )}

            <button
              onClick={submit}
              disabled={busy || !username.trim() || !password || (mode === 'register' && !name.trim())}
              className="w-full cursor-pointer rounded-sm bg-dai px-4 py-2.5 font-serif-sc text-sm font-bold tracking-[0.35em] text-paper shadow-[0_3px_0_var(--color-dai-deep)] transition-all hover:bg-dai-deep active:translate-y-0.5 active:shadow-none disabled:opacity-40"
            >
              {busy ? '验证中…' : mode === 'login' ? '进入门诊' : '建立病历'}
            </button>

            <p className="pt-1 text-center font-mono-id text-[9.5px] tracking-wider text-ink-faint/60">
              DEMO 级认证 · 密码加盐哈希存储
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  )
}
