import { describe, expect, it } from 'vitest'

import { normalizeApiError } from '../api/errors'

function axiosError(status: number, data: unknown) {
  return {
    isAxiosError: true,
    message: 'Request failed',
    response: { status, data },
  }
}

describe('normalizeApiError', () => {
  it('maps a string detail and status', () => {
    const normalized = normalizeApiError(
      axiosError(403, { detail: 'Forbidden' }),
    )
    expect(normalized.status).toBe(403)
    expect(normalized.message).toBe('Forbidden')
    expect(normalized.issues).toEqual([])
  })

  it('maps validation issues without requiring input fields', () => {
    const normalized = normalizeApiError(
      axiosError(422, {
        detail: [
          {
            type: 'timezone_aware',
            loc: ['body', 'events', 0, 'timestamp'],
            msg: 'Input should have timezone info',
          },
        ],
      }),
    )
    expect(normalized.status).toBe(422)
    expect(normalized.issues).toHaveLength(1)
    expect(normalized.message).toContain('events.0.timestamp')
  })

  it('maps network failures to an actionable message', () => {
    const normalized = normalizeApiError({
      isAxiosError: true,
      message: 'Network Error',
    })
    expect(normalized.status).toBeUndefined()
    expect(normalized.message).toContain('无法连接后端服务')
  })
})
