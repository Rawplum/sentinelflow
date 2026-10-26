import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import {
  investigationPending,
  investigationRunning,
  investigationSucceeded,
} from '../test/msw/handlers'
import { server } from '../test/msw/server'
import { adminAuth, analystAuth, renderApp } from '../test/utils'

const ALERT_ID = '55555555-5555-4555-8555-555555555555'
const REPORT_PATH = `/alerts/${ALERT_ID}/report`

describe('InvestigationPanel', () => {
  it('does not offer the start button to analysts', async () => {
    renderApp(REPORT_PATH, analystAuth)

    expect(await screen.findByText('AI 调查')).toBeInTheDocument()
    expect(
      screen.getByText('仅管理员可以发起 AI 调查。分析员可以查看已有调查结果。'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /启动 AI 调查|重新调查/ }),
    ).not.toBeInTheDocument()
  })

  it('queues an investigation and shows the pending state', async () => {
    const user = userEvent.setup()
    renderApp(REPORT_PATH, adminAuth)

    const start = await screen.findByRole('button', { name: /启动 AI 调查/ })
    await user.click(start)

    expect(await screen.findByText('排队中')).toBeInTheDocument()
    expect(
      screen.getByText(
        '任务已持久化入队，等待工作进程领取。刷新或关闭页面不会丢失。',
      ),
    ).toBeInTheDocument()
    // The investigation id becomes the source of truth in the URL.
    expect(screen.getByTitle(investigationPending.id)).toBeInTheDocument()
    // A queued task must not be submitted twice from the UI.
    expect(
      screen.getByRole('button', { name: /已排队，等待执行/ }),
    ).toBeDisabled()
  })

  it('shows the running state for a claimed task', async () => {
    renderApp(
      `${REPORT_PATH}?investigation=${investigationRunning.id}`,
      adminAuth,
    )

    expect(await screen.findByText('进行中')).toBeInTheDocument()
    expect(
      screen.getByText('调查正在后台执行，页面会自动刷新状态。刷新页面不会中断调查。'),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /调查进行中/ }),
    ).toBeDisabled()
  })

  it('renders steps, tool calls and the draft report evidence', async () => {
    renderApp(
      `${REPORT_PATH}?investigation=${investigationSucceeded.id}`,
      adminAuth,
    )

    expect(await screen.findByText('已完成')).toBeInTheDocument()
    expect(screen.getByText('执行步骤')).toBeInTheDocument()
    expect(screen.getByText('工具调用')).toBeInTheDocument()
    expect(screen.getByText('get_related_events')).toBeInTheDocument()
    expect(screen.getByText('给出结论')).toBeInTheDocument()
    expect(screen.getByText('145 ms')).toBeInTheDocument()

    expect(
      await screen.findByText('调查产出的草稿报告'),
    ).toBeInTheDocument()
    // Evidence citations are rendered from the real report payload.
    expect(
      screen.getByText('33333333-3333-4333-8333-333333333333'),
    ).toBeInTheDocument()
  })

  it('resumes an in-flight investigation after a page refresh', async () => {
    // Rendering straight at the URL simulates F5: no in-memory state exists.
    renderApp(
      `${REPORT_PATH}?investigation=${investigationRunning.id}`,
      adminAuth,
    )

    expect(await screen.findByText('进行中')).toBeInTheDocument()
    expect(screen.getByTitle(investigationRunning.id)).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /调查进行中/ }),
    ).toBeDisabled()
  })

  it('shows the failure reason and offers a retry', async () => {
    server.use(
      http.get('*/api/v1/investigations/:investigationId', () =>
        HttpResponse.json({
          ...investigationSucceeded,
          status: 'failed',
          report_id: null,
          error: 'Model request failed: TimeoutError',
        }),
      ),
    )

    renderApp(
      `${REPORT_PATH}?investigation=${investigationSucceeded.id}`,
      adminAuth,
    )

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('Model request failed: TimeoutError')
    expect(screen.queryByText('进行中')).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: /重新调查/ }),
    ).toBeInTheDocument()
  })

  it('reports a configuration error instead of pretending success', async () => {
    server.use(
      http.post('*/api/v1/alerts/:alertId/investigations', () =>
        HttpResponse.json(
          { detail: 'AI agent is not configured' },
          { status: 503 },
        ),
      ),
    )

    const user = userEvent.setup()
    renderApp(REPORT_PATH, adminAuth)

    const start = await screen.findByRole('button', { name: /启动 AI 调查/ })
    await user.click(start)

    expect(
      await screen.findByText(/AI agent is not configured/),
    ).toBeInTheDocument()
    // No fabricated result appears.
    expect(screen.queryByText('已完成')).not.toBeInTheDocument()
  })

  it('surfaces a load error for an unknown investigation', async () => {
    renderApp(
      `${REPORT_PATH}?investigation=99999999-9999-4999-8999-999999999999`,
      adminAuth,
    )

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('无法读取调查')
    expect(screen.getByRole('button', { name: /重试/ })).toBeInTheDocument()
  })
})
