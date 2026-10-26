import type { EventOutcome, SecurityEventCreate } from '../api/types'

const VALID_OUTCOMES = new Set<EventOutcome>(['success', 'failure', 'unknown'])
const REQUIRED_KEYS = [
  'event_id',
  'timestamp',
  'event_type',
  'action',
  'outcome',
  'raw_message',
  'source',
] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function validateEvent(value: unknown, index: number): SecurityEventCreate {
  if (!isRecord(value)) {
    throw new Error(`第 ${index + 1} 条不是 JSON 对象。`)
  }
  for (const key of REQUIRED_KEYS) {
    if (!(key in value)) {
      throw new Error(`第 ${index + 1} 条缺少字段 ${key}。`)
    }
  }
  if (typeof value.event_id !== 'string') {
    throw new Error(`第 ${index + 1} 条 event_id 必须是字符串。`)
  }
  if (
    typeof value.timestamp !== 'string' ||
    Number.isNaN(Date.parse(value.timestamp))
  ) {
    throw new Error(`第 ${index + 1} 条 timestamp 不是有效时间。`)
  }
  if (typeof value.event_type !== 'string' || !value.event_type) {
    throw new Error(`第 ${index + 1} 条 event_type 不能为空。`)
  }
  if (typeof value.action !== 'string' || !value.action) {
    throw new Error(`第 ${index + 1} 条 action 不能为空。`)
  }
  if (
    typeof value.outcome !== 'string' ||
    !VALID_OUTCOMES.has(value.outcome as EventOutcome)
  ) {
    throw new Error(`第 ${index + 1} 条 outcome 必须是 success/failure/unknown。`)
  }
  if (typeof value.raw_message !== 'string' || !value.raw_message) {
    throw new Error(`第 ${index + 1} 条 raw_message 不能为空。`)
  }
  if (value.raw_message.length > 8192) {
    throw new Error(`第 ${index + 1} 条 raw_message 超过 8192 字符。`)
  }
  if (typeof value.source !== 'string' || !value.source) {
    throw new Error(`第 ${index + 1} 条 source 不能为空。`)
  }
  return value as unknown as SecurityEventCreate
}

export function parseEventText(text: string): SecurityEventCreate[] {
  const trimmed = text.trim()
  if (!trimmed) {
    throw new Error('请输入或上传事件数据。')
  }

  let parsed: unknown
  const lines = trimmed.split(/\r?\n/).filter((line) => line.trim())
  const looksLikeJsonl =
    lines.length > 1 && lines.every((line) => line.trim().startsWith('{'))

  if (looksLikeJsonl) {
    parsed = lines.map((line, index) => {
      try {
        return JSON.parse(line) as unknown
      } catch {
        throw new Error(`第 ${index + 1} 行 JSON 解析失败。`)
      }
    })
  } else {
    try {
      parsed = JSON.parse(trimmed)
    } catch (error) {
      const message = error instanceof Error ? error.message : 'JSON 解析失败'
      throw new Error(`JSON 解析失败：${message}`)
    }
  }

  let items: unknown[]
  if (Array.isArray(parsed)) {
    items = parsed
  } else if (isRecord(parsed) && Array.isArray(parsed.events)) {
    items = parsed.events
  } else {
    items = [parsed]
  }

  if (items.length === 0) {
    throw new Error('事件数组不能为空。')
  }
  if (items.length > 500) {
    throw new Error(`单次最多导入 500 条事件，当前为 ${items.length} 条。`)
  }

  return items.map((item, index) => validateEvent(item, index))
}
