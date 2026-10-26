import { apiClient } from './client'
import type { CurrentUser, TokenResponse } from './types'

export async function login(
  username: string,
  password: string,
): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>('/auth/login', {
    username,
    password,
  })
  return response.data
}

export async function getCurrentUser(): Promise<CurrentUser> {
  const response = await apiClient.get<CurrentUser>('/auth/me')
  return response.data
}
