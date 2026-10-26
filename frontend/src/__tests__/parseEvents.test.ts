import { describe, expect, it } from 'vitest'

import { parseEventText } from '../lib/parseEvents'

const event = {
  event_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  timestamp: '2026-10-19T09:00:00Z',
  event_type: 'authentication',
  username: 'alice.demo',
  source_ip: '198.51.100.10',
  asset_id: 'workstation-01',
  action: 'login',
  outcome: 'failure',
  raw_message: 'synthetic failure',
  source: 'synthetic-auth',
}

describe('parseEventText', () => {
  it('parses a JSON array', () => {
    expect(parseEventText(JSON.stringify([event]))).toHaveLength(1)
  })

  it('parses JSONL', () => {
    const parsed = parseEventText(`${JSON.stringify(event)}\n${JSON.stringify(event)}`)
    expect(parsed).toHaveLength(2)
  })

  it('rejects a missing required field', () => {
    const missing: Record<string, unknown> = { ...event }
    delete missing.action
    expect(() => parseEventText(JSON.stringify([missing]))).toThrow(
      '缺少字段 action',
    )
  })

  it('rejects more than 500 events', () => {
    const items = Array.from({ length: 501 }, (_, index) => ({
      ...event,
      event_id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
    }))
    expect(() => parseEventText(JSON.stringify(items))).toThrow('最多导入 500 条')
  })
})
