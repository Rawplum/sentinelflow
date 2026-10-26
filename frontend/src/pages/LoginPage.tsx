import { Eye, EyeOff, LockKeyhole, Radar, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { normalizeApiError } from '../api/errors'
import { useAuth } from '../auth/useAuth'
import { Button } from '../components/ui/Button'
import { FormField } from '../components/ui/FormField'
import { LOCAL_ONLY_NOTICE } from '../lib/constants'

interface LoginState {
  from?: { pathname?: string; search?: string }
  reason?: string
}

export function LoginPage() {
  const { login, isAuthenticated, isLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as LoginState | null

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const redirectTo = state?.from?.pathname
    ? `${state.from.pathname}${state.from.search ?? ''}`
    : '/dashboard'

  if (!isLoading && isAuthenticated) {
    return <Navigate to={redirectTo} replace />
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)

    if (!username.trim() || !password) {
      setError('请输入用户名和密码。')
      return
    }

    setSubmitting(true)
    try {
      await login(username.trim(), password)
      navigate(redirectTo, { replace: true })
    } catch (cause) {
      const normalized = normalizeApiError(cause)
      setError(
        normalized.status === 401
          ? '用户名或密码错误。'
          : normalized.status === 503
            ? '认证服务未配置，请检查后端的 JWT_SECRET。'
            : normalized.message,
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="sf-login">
      <section className="sf-login-aside">
        <div className="sf-login-brand">
          <div className="sf-brand-mark sf-brand-mark-lg" aria-hidden="true">
            <ShieldCheck size={30} />
          </div>
          <div>
            <p className="sf-eyebrow">SECURITY OPERATIONS</p>
            <h1>SentinelFlow</h1>
            <p className="sf-login-tagline">
              从安全事件到可复核结论的确定性研判控制台。
            </p>
          </div>
        </div>

        <div className="sf-login-features">
          <div>
            <Radar size={18} aria-hidden="true" />
            <span>AUTH-001 五窗口认证失败检测</span>
          </div>
          <div>
            <LockKeyhole size={18} aria-hidden="true" />
            <span>JWT 认证与后端 RBAC 强制校验</span>
          </div>
          <div>
            <ShieldCheck size={18} aria-hidden="true" />
            <span>证据引用与调查报告审计闭环</span>
          </div>
        </div>

        <p className="sf-login-local">{LOCAL_ONLY_NOTICE}</p>
      </section>

      <section className="sf-login-panel">
        <div className="sf-login-card">
          <div className="sf-login-card-header">
            <span className="sf-local-badge">LOCAL DEMO</span>
            <h2>登录控制台</h2>
            <p>使用本地管理员或分析员账户继续。</p>
          </div>

          {state?.reason === 'expired' ? (
            <div className="sf-alert sf-alert-info" role="status">
              会话已过期，请重新登录。
            </div>
          ) : null}

          {error ? (
            <div className="sf-alert sf-alert-error" role="alert">
              {error}
            </div>
          ) : null}

          <form className="sf-form" onSubmit={handleSubmit} noValidate>
            <FormField label="用户名" htmlFor="username">
              <input
                id="username"
                className="sf-input"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                autoFocus
                spellCheck={false}
              />
            </FormField>

            <FormField label="密码" htmlFor="password">
              <div className="sf-input-with-action">
                <input
                  id="password"
                  className="sf-input"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  className="sf-input-action"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </FormField>

            <Button
              type="submit"
              variant="primary"
              loading={submitting}
              className="sf-btn-block"
            >
              {submitting ? '正在登录…' : '登录'}
            </Button>
          </form>

          <details className="sf-login-security">
            <summary>关于令牌存储</summary>
            <p>
              演示环境将访问令牌保存在 sessionStorage，关闭标签页后清除。该方式仍可能受 XSS
              影响，不应视为生产最佳实践；生产环境应使用 HttpOnly Cookie、短期令牌、CSP
              和完整的令牌撤销机制。
            </p>
          </details>

          <p className="sf-login-footnote">
            没有公开注册入口。管理员账户由后端本地 CLI 创建。
          </p>
        </div>
      </section>
    </main>
  )
}
