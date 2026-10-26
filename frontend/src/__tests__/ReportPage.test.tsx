import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { report } from '../test/msw/handlers'
import { server } from '../test/msw/server'
import { adminAuth, analystAuth, renderApp } from '../test/utils'

const ALERT_ID = '55555555-5555-4555-8555-555555555555'

describe('ReportPage', () => {
  it('renders report sections from the API response', async () => {
    renderApp(`/alerts/${ALERT_ID}/report`, analystAuth)

    expect(
      await screen.findByText(
        "Rule AUTH-001 identified 5 failed authentication attempts for user 'alice.demo' from 198.51.100.10.",
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('证据事件')).toBeInTheDocument()
    expect(screen.getByText('事件时间线')).toBeInTheDocument()
    expect(screen.getByText('判断依据')).toBeInTheDocument()
    expect(screen.getByText('推荐处置措施')).toBeInTheDocument()
    expect(screen.getByText('检测局限性')).toBeInTheDocument()
    expect(
      screen.getByText('Verify whether the source IP is expected for this user.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'This rule detects a pattern; it does not prove that a system was compromised.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /定稿|保存/ }),
    ).not.toBeInTheDocument()
  })

  it('shows a not-found state for unknown alerts', async () => {
    renderApp('/alerts/00000000-0000-4000-8000-000000000000/report', analystAuth)

    expect(await screen.findByText('告警不存在')).toBeInTheDocument()
  })

  it('loads alert metadata from the API without router state', async () => {
    // Rendering straight at the report URL simulates a page refresh: no
    // history state is available, so the title and status must come from the
    // alert detail endpoint.
    renderApp(`/alerts/${ALERT_ID}/report`, analystAuth)

    expect(
      await screen.findByRole('heading', { name: 'Suspicious login activity' }),
    ).toBeInTheDocument()
    expect(screen.getByText('待处理')).toBeInTheDocument()
    expect(screen.getByText(/证据数 5/)).toBeInTheDocument()
    expect(
      screen.queryByText(/直接打开报告链接时/),
    ).not.toBeInTheDocument()
  })

  it('shows a truncation notice when evidence is capped', async () => {
    server.use(
      http.get('*/api/v1/alerts/:alertId/report', () =>
        HttpResponse.json({
          ...report,
          evidence_total: 150,
          evidence_truncated: true,
        }),
      ),
    )

    renderApp(`/alerts/${ALERT_ID}/report`, analystAuth)

    expect(
      await screen.findByText(/1 \/ 150 条 · 已截断/),
    ).toBeInTheDocument()
  })

  it('labels the live report as rule-generated and links back to the alert', async () => {
    renderApp('/alerts/55555555-5555-4555-8555-555555555555/report', adminAuth)

    expect(await screen.findByText('确定性规则生成')).toBeInTheDocument()

    const back = screen.getByRole('link', { name: /返回告警详情/ })
    expect(back).toHaveAttribute(
      'href',
      '/alerts/55555555-5555-4555-8555-555555555555',
    )
  })
})
