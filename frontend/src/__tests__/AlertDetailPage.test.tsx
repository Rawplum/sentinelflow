import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '../test/msw/server'
import { adminAuth, renderApp } from '../test/utils'

const ALERT_ID = '55555555-5555-4555-8555-555555555555'
const DETAIL_PATH = `/alerts/${ALERT_ID}`

describe('AlertDetailPage', () => {
  it('renders the alert, its evidence and the investigation entry point', async () => {
    renderApp(DETAIL_PATH, adminAuth)

    expect(
      await screen.findByRole('heading', { name: 'Suspicious login activity' }),
    ).toBeInTheDocument()

    // Metadata comes from GET /alerts/{id}, not from router state.
    expect(screen.getByText('告警信息')).toBeInTheDocument()
    expect(screen.getByText('AUTH-001')).toBeInTheDocument()

    // Evidence comes from GET /alerts/{id}/evidence.
    const evidenceCard = screen.getByText('关联证据').closest('.sf-card')
    expect(evidenceCard).not.toBeNull()
    expect(
      within(evidenceCard as HTMLElement).getByText('alice.demo'),
    ).toBeInTheDocument()

    // The investigation panel is present and gated on the admin role.
    expect(screen.getByText('AI 调查')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /启动 AI 调查/ }),
    ).toBeInTheDocument()
  })

  it('offers a link to the report', async () => {
    renderApp(DETAIL_PATH, adminAuth)

    const link = await screen.findByRole('link', { name: /查看报告/ })
    expect(link).toHaveAttribute('href', `${DETAIL_PATH}/report`)
  })

  it('shows a not-found state for an unknown alert', async () => {
    renderApp('/alerts/99999999-9999-4999-8999-999999999999', adminAuth)

    expect(await screen.findByText('告警不存在')).toBeInTheDocument()
  })

  it('shows a retryable error when the API fails', async () => {
    server.use(
      http.get('*/api/v1/alerts/:alertId', () =>
        HttpResponse.json({ detail: 'boom' }, { status: 500 }),
      ),
    )

    renderApp(DETAIL_PATH, adminAuth)

    expect(await screen.findByText(/无法加载告警/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /重试/ })).toBeInTheDocument()
  })

  it('does not offer the investigation button to analysts', async () => {
    renderApp(DETAIL_PATH, {
      ...adminAuth,
      user: { ...adminAuth.user!, role: 'analyst' },
      isAdmin: false,
    })

    expect(
      await screen.findByText('仅管理员可以发起 AI 调查。分析员可以查看已有调查结果。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /启动 AI 调查/ }),
    ).not.toBeInTheDocument()
  })
})
