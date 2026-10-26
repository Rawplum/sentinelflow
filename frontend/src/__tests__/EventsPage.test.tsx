import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { server } from '../test/msw/server'
import {
  adminAuth,
  analystAuth,
  renderApp,
} from '../test/utils'

describe('EventsPage', () => {
  it('renders events, opens details, and shows admin import', async () => {
    const user = userEvent.setup()
    renderApp('/events', adminAuth)

    expect(await screen.findByText('alice.demo')).toBeInTheDocument()
    expect(screen.getByText('共 2 条，当前显示 2 条')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '导入事件' }),
    ).toBeInTheDocument()

    await user.click(screen.getByText('alice.demo'))

    expect(await screen.findByText('事件详情')).toBeInTheDocument()
    expect(
      screen.getByText('synthetic event: failed password for alice.demo'),
    ).toBeInTheDocument()
  })

  it('hides import controls from analysts', async () => {
    renderApp('/events', analystAuth)

    expect(await screen.findByText('alice.demo')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '导入事件' }),
    ).not.toBeInTheDocument()
  })

  it('shows an empty state when no events exist', async () => {
    server.use(
      http.get('*/api/v1/events', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    )

    renderApp('/events', adminAuth)

    expect(
      await screen.findByText('暂无事件。可以导入合成安全日志后查看。'),
    ).toBeInTheDocument()
  })

  it('shows an error state when the API fails', async () => {
    server.use(
      http.get('*/api/v1/events', () =>
        HttpResponse.json(
          { detail: 'Database operation failed' },
          { status: 500 },
        ),
      ),
    )

    renderApp('/events', adminAuth)

    expect(await screen.findByText('请求失败')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '重试' }),
    ).toBeInTheDocument()
  })
})
