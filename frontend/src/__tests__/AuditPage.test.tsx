import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import {
  adminAuth,
  analystAuth,
  renderApp,
} from '../test/utils'

describe('AuditPage', () => {
  it('renders audit records and filters by action for admins', async () => {
    const user = userEvent.setup()
    renderApp('/audit', adminAuth)

    expect(await screen.findByText('events.import')).toBeInTheDocument()
    expect(screen.getByText('导入事件')).toBeInTheDocument()
    expect(screen.getAllByText('admin.test').length).toBeGreaterThan(0)

    await user.selectOptions(screen.getByLabelText('操作类型'), 'auth.login')

    expect(await screen.findByText('auth.login')).toBeInTheDocument()
    expect(screen.queryByText('events.import')).not.toBeInTheDocument()
  })

  it('blocks analysts at the route guard', async () => {
    renderApp('/audit', analystAuth)

    expect(await screen.findByText('无权限访问')).toBeInTheDocument()
    expect(screen.queryByText('审计日志')).not.toBeInTheDocument()
  })
})
