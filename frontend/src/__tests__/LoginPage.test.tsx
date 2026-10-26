import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { makeAuth, renderApp, unauthenticatedAuth } from '../test/utils'

describe('LoginPage', () => {
  it('submits credentials and hides registration', async () => {
    const login = vi.fn().mockResolvedValue(undefined)
    const auth = makeAuth({
      ...unauthenticatedAuth,
      login,
    })
    const user = userEvent.setup()

    renderApp('/login', auth)

    expect(screen.getByRole('heading', { name: '登录控制台' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /注册/ })).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('用户名'), 'admin.test')
    await user.type(screen.getByLabelText('密码'), 'correct-password-123')
    await user.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith('admin.test', 'correct-password-123')
    })
  })

  it('shows a generic message for invalid credentials', async () => {
    const login = vi.fn().mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed',
      response: {
        status: 401,
        data: { detail: 'Invalid username or password' },
      },
    })
    const auth = makeAuth({
      ...unauthenticatedAuth,
      login,
    })
    const user = userEvent.setup()

    renderApp('/login', auth)
    await user.type(screen.getByLabelText('用户名'), 'admin.test')
    await user.type(screen.getByLabelText('密码'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '用户名或密码错误。',
    )
  })

  it('shows authentication configuration errors', async () => {
    const login = vi.fn().mockRejectedValue({
      isAxiosError: true,
      message: 'Request failed',
      response: {
        status: 503,
        data: { detail: 'Authentication is not configured' },
      },
    })
    const auth = makeAuth({
      ...unauthenticatedAuth,
      login,
    })
    const user = userEvent.setup()

    renderApp('/login', auth)
    await user.type(screen.getByLabelText('用户名'), 'admin.test')
    await user.type(screen.getByLabelText('密码'), 'any-password')
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      '认证服务未配置',
    )
  })
})
