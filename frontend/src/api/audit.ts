import { apiClient } from './client'
import type { AuditLog, Paginated } from './types'

export async function listAuditLogs(
  limit: number,
  offset: number,
  action?: string,
): Promise<Paginated<AuditLog>> {
  const response = await apiClient.get<Paginated<AuditLog>>('/audit-logs', {
    params: {
      limit,
      offset,
      ...(action ? { action } : {}),
    },
  })
  return response.data
}
