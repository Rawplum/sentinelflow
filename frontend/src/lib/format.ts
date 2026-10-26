import { AUDIT_ACTION_LABELS } from './constants'

const dateTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const numberFormatter = new Intl.NumberFormat('zh-CN')

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return dateTimeFormatter.format(date)
}

export function formatNumber(value: number): string {
  return numberFormatter.format(value)
}

export function formatPercent(value: number, total: number): string {
  if (total <= 0) return '0%'
  return `${Math.round((value / total) * 100)}%`
}

export function shortId(value: string, length = 10): string {
  if (value.length <= length) return value
  return `${value.slice(0, length)}…`
}

export function formatAuditAction(action: string): string {
  return AUDIT_ACTION_LABELS[action] ?? action
}

export function formatJson(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function formatNullable(value: string | null | undefined): string {
  return value && value.trim() ? value : '—'
}
