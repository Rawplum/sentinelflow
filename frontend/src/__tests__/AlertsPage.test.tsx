import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '../test/msw/server'

import {
  adminAuth,
  analystAuth,
  renderApp,
} from '../test/utils'

describe('AlertsPage', () => {
  it('shows alerts and lets admins run detection', async () => {
    const user = userEvent.setup()
    renderApp('/alerts', adminAuth)

    expect(
      await screen.findByText('Suspicious login activity'),
    ).toBeInTheDocument()
    const table = await screen.findByRole('table')
    expect(within(table).getByText('高')).toBeInTheDocument()
    expect(within(table).getByText('待处理')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '运行检测' }))

    expect(await screen.findByText('检测完成。')).toBeInTheDocument()
    expect(screen.getByText(/创建 1 个告警/)).toBeInTheDocument()
  })

  it('hides detection controls from analysts', async () => {
    renderApp('/alerts', analystAuth)

    expect(
      await screen.findByText('Suspicious login activity'),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '运行检测' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/分析员只读视图/)).toBeInTheDocument()
  })

  it('sends the status filter to the backend', async () => {
    let captured: string | null = null
    server.use(
      http.get('*/api/v1/alerts', ({ request }) => {
        captured = new URL(request.url).searchParams.get('status')
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 })
      }),
    )

    const user = userEvent.setup()
    renderApp('/alerts', adminAuth)

    await user.selectOptions(screen.getByLabelText('状态'), 'closed')

    await waitFor(() => expect(captured).toBe('closed'))
    expect(await screen.findByText('暂无告警。导入事件并运行检测后会出现结果。')).toBeInTheDocument()
  })

  it('sends the severity filter and can clear it', async () => {
    const seen: (string | null)[] = []
    server.use(
      http.get('*/api/v1/alerts', ({ request }) => {
        seen.push(new URL(request.url).searchParams.get('severity'))
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 })
      }),
    )

    const user = userEvent.setup()
    renderApp('/alerts', adminAuth)

    await user.selectOptions(screen.getByLabelText('严重性'), 'critical')
    await waitFor(() => expect(seen.at(-1)).toBe('critical'))

    await user.click(screen.getByRole('button', { name: '清除筛选' }))
    await waitFor(() => expect(seen.at(-1)).toBeNull())
  })

  it('links to the investigation report', async () => {
    renderApp('/alerts', adminAuth)

    const links = await screen.findAllByRole('link', { name: '查看报告' })
    expect(links[0]).toHaveAttribute(
      'href',
      '/alerts/55555555-5555-4555-8555-555555555555/report',
    )
  })
})
