import { apiClient } from './client'
import type { Investigation } from './types'

export async function startInvestigation(
  alertId: string,
): Promise<Investigation> {
  const response = await apiClient.post<Investigation>(
    `/alerts/${alertId}/investigations`,
  )
  return response.data
}

export async function getInvestigation(
  investigationId: string,
): Promise<Investigation> {
  const response = await apiClient.get<Investigation>(
    `/investigations/${investigationId}`,
  )
  return response.data
}
