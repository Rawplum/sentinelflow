import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

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
    expect(screen.getByText('高')).toBeInTheDocument()
    expect(screen.getByText('待处理')).toBeInTheDocument()

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

  it('links to the investigation report', async () => {
    renderApp('/alerts', adminAuth)

    const links = await screen.findAllByRole('link', { name: '查看报告' })
    expect(links[0]).toHaveAttribute(
      'href',
      '/alerts/55555555-5555-4555-8555-555555555555/report',
    )
  })
})
