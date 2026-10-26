import { apiClient } from './client'
import type {
  Alert,
  AlertDetail,
  AlertStatus,
  InvestigationReport,
  InvestigationReportList,
  InvestigationReportVersion,
  Paginated,
  SecurityEvent,
} from './types'

export interface AlertFilters {
  status?: string
  severity?: string
}

export async function listAlerts(
  limit: number,
  offset: number,
  filters: AlertFilters = {},
): Promise<Paginated<Alert>> {
  const response = await apiClient.get<Paginated<Alert>>('/alerts', {
    params: {
      limit,
      offset,
      ...(filters.status ? { status: filters.status } : {}),
      ...(filters.severity ? { severity: filters.severity } : {}),
    },
  })
  return response.data
}

export async function getAlertEvidence(
  alertId: string,
  limit = 10,
  offset = 0,
): Promise<Paginated<SecurityEvent>> {
  const response = await apiClient.get<Paginated<SecurityEvent>>(
    `/alerts/${alertId}/evidence`,
    { params: { limit, offset } },
  )
  return response.data
}

export async function getAlert(alertId: string): Promise<AlertDetail> {
  const response = await apiClient.get<AlertDetail>(`/alerts/${alertId}`)
  return response.data
}

export async function updateAlertStatus(
  alertId: string,
  status: AlertStatus,
  reason?: string,
): Promise<AlertDetail> {
  const response = await apiClient.patch<AlertDetail>(`/alerts/${alertId}`, {
    status,
    ...(reason ? { reason } : {}),
  })
  return response.data
}

export async function getAlertReport(
  alertId: string,
  params?: { evidence_limit?: number; evidence_offset?: number },
): Promise<InvestigationReport> {
  const response = await apiClient.get<InvestigationReport>(
    `/alerts/${alertId}/report`,
    { params },
  )
  return response.data
}

export async function getReportVersion(
  reportId: string,
): Promise<InvestigationReportVersion> {
  const response = await apiClient.get<InvestigationReportVersion>(
    `/reports/${reportId}`,
  )
  return response.data
}

export async function listReportVersions(
  alertId: string,
): Promise<InvestigationReportList> {
  const response = await apiClient.get<InvestigationReportList>(
    `/alerts/${alertId}/reports`,
  )
  return response.data
}

export async function createReportVersion(
  alertId: string,
): Promise<InvestigationReportVersion> {
  const response = await apiClient.post<InvestigationReportVersion>(
    `/alerts/${alertId}/reports`,
    {},
  )
  return response.data
}

export async function finalizeReport(
  reportId: string,
): Promise<InvestigationReportVersion> {
  const response = await apiClient.post<InvestigationReportVersion>(
    `/reports/${reportId}/finalize`,
  )
  return response.data
}
