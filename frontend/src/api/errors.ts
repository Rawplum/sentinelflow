import axios from 'axios'

export interface ValidationIssue {
  type: string
  loc: (string | number)[]
  msg: string
}

export interface NormalizedApiError {
  status?: number
  message: string
  issues: ValidationIssue[]
}

function isValidationIssue(value: unknown): value is ValidationIssue {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return typeof candidate.msg === 'string'
}

function issueMessage(issue: ValidationIssue): string {
  const location = issue.loc.filter((part) => part !== 'body').join('.')
  return location ? `${location}: ${issue.msg}` : issue.msg
}

export function normalizeApiError(error: unknown): NormalizedApiError {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    const data: unknown = error.response?.data

    if (typeof data === 'object' && data !== null && 'detail' in data) {
      const detail = (data as { detail: unknown }).detail

      if (typeof detail === 'string') {
        return { status, message: detail, issues: [] }
      }

      if (Array.isArray(detail)) {
        const issues = detail.filter(isValidationIssue)
        return {
          status,
          message: issues.length
            ? issues.map(issueMessage).join('；')
            : '请求参数无效，请检查输入。',
          issues,
        }
      }
    }

    if (status === 401) {
      return { status, message: '登录已失效，请重新登录。', issues: [] }
    }
    if (status === 403) {
      return { status, message: '当前账户没有权限执行此操作。', issues: [] }
    }
    if (status === 404) {
      return { status, message: '请求的资源不存在。', issues: [] }
    }
    if (status === 422) {
      return { status, message: '请求参数无效，请检查输入。', issues: [] }
    }
    if (status === 503) {
      return {
        status,
        message: '认证服务未配置，请检查后端的 JWT_SECRET。',
        issues: [],
      }
    }
    if (status && status >= 500) {
      return { status, message: '服务暂时不可用，请稍后重试。', issues: [] }
    }
    if (!error.response) {
      return {
        status: undefined,
        message: '无法连接后端服务，请确认 API 地址和 Vite 代理配置。',
        issues: [],
      }
    }
    return {
      status,
      message: error.message || '请求失败，请稍后重试。',
      issues: [],
    }
  }

  if (error instanceof Error) {
    return { message: error.message, issues: [] }
  }

  return { message: '发生未知错误，请稍后重试。', issues: [] }
}
