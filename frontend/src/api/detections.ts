import { apiClient } from './client'
import type { DetectionRunResponse } from './types'

export async function runDetection(): Promise<DetectionRunResponse> {
  const response = await apiClient.post<DetectionRunResponse>('/detections/run')
  return response.data
}
