import { apiClient } from './client'
import type {
  EventImportResponse,
  Paginated,
  SecurityEvent,
  SecurityEventCreate,
} from './types'

export async function listEvents(
  limit: number,
  offset: number,
): Promise<Paginated<SecurityEvent>> {
  const response = await apiClient.get<Paginated<SecurityEvent>>('/events', {
    params: { limit, offset },
  })
  return response.data
}

export async function importEvents(
  events: SecurityEventCreate[],
): Promise<EventImportResponse> {
  const response = await apiClient.post<EventImportResponse>('/events/import', {
    events,
  })
  return response.data
}
