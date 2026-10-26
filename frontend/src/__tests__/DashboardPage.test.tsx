import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  adminAuth,
  analystAuth,
  renderApp,
  unauthenticatedAuth,
} from '../test/utils'

describe('DashboardPage and route guards', () => {
  it('shows overview data and admin operations', async () => {
    renderApp('/dashboard', adminAuth)

    expect(
      await screen.findByText('安全运营仪表盘'),
    ).toBeInTheDocument()
    expect(screen.getByText('事件总量')).toBeInTheDocument()
    expect(screen.getByText('告警总量')).toBeInTheDocument()
    expect(
      await screen.findByText('Suspicious login activity'),
    ).toBeInTheDocument()
    expect(screen.getByText('管理员操作')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: '运行检测' }),
    ).toBeInTheDocument()
  })

  it('renders a read-only dashboard for analysts', async () => {
    renderApp('/dashboard', analystAuth)

    expect(
      await screen.findByText('安全运营仪表盘'),
    ).toBeInTheDocument()
    expect(screen.getByText(/分析员只读视图/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: '运行检测' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('审计仅管理员可见')).toBeInTheDocument()
  })

  it('redirects unauthenticated users to login', async () => {
    renderApp('/events', unauthenticatedAuth)

    expect(
      await screen.findByRole('heading', { name: '登录控制台' }),
    ).toBeInTheDocument()
  })
})
