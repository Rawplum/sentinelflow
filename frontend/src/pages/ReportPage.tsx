import { useQuery } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Clock3,
  FileText,
  History,
  ListChecks,
} from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { getAlert, getAlertReport, listReportVersions } from '../api/alerts'
import { normalizeApiError } from '../api/errors'
import { SeverityBadge, StatusBadge } from '../components/domain/Badges'
import { EvidenceTable } from '../components/domain/EvidenceTable'
import { InvestigationPanel } from '../components/domain/InvestigationPanel'
import { Timeline } from '../components/domain/Timeline'
import { PageHeader } from '../components/layout/PageHeader'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { formatDateTime, shortId } from '../lib/format'

const REPORT_STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  finalized: '已定稿',
  superseded: '已被新版本取代',
}

export function ReportPage() {
  const { alertId } = useParams<{ alertId: string }>()

  // Alert metadata comes from the API, not from router state, so a page
  // refresh or a shared link renders the same content as in-app navigation.
  const alertQuery = useQuery({
    queryKey: ['alert', alertId],
    queryFn: () => {
      if (!alertId) throw new Error('缺少告警 ID')
      return getAlert(alertId)
    },
    enabled: Boolean(alertId),
  })

  const reportQuery = useQuery({
    queryKey: ['report', alertId],
    queryFn: () => {
      if (!alertId) throw new Error('缺少告警 ID')
      return getAlertReport(alertId)
    },
    enabled: Boolean(alertId),
  })

  const versionsQuery = useQuery({
    queryKey: ['report-versions', alertId],
    queryFn: () => {
      if (!alertId) throw new Error('缺少告警 ID')
      return listReportVersions(alertId)
    },
    enabled: Boolean(alertId),
  })

  const error = alertQuery.isError
    ? normalizeApiError(alertQuery.error)
    : reportQuery.isError
      ? normalizeApiError(reportQuery.error)
      : null

  if (alertQuery.isLoading || reportQuery.isLoading) {
    return (
      <div className="sf-page">
        <Spinner label="正在生成调查报告…" />
      </div>
    )
  }

  if (error?.status === 404) {
    return (
      <div className="sf-page">
        <EmptyState
          title="告警不存在"
          message="该告警可能已被删除，或链接中的 ID 不正确。"
        />
      </div>
    )
  }

  if (error) {
    return (
      <div className="sf-page">
        <ErrorState
          message={error.message}
          onRetry={() => {
            void alertQuery.refetch()
            void reportQuery.refetch()
          }}
        />
      </div>
    )
  }

  if (!alertQuery.data || !reportQuery.data) {
    return (
      <div className="sf-page">
        <EmptyState title="没有报告数据" message="请从告警列表重新进入。" />
      </div>
    )
  }

  const alert = alertQuery.data
  const report = reportQuery.data
  const versions = versionsQuery.data?.items ?? []
  const truncated = report.evidence_truncated

  return (
    <div className="sf-page">
      <Link to="/alerts" className="sf-back-link">
        <ArrowLeft size={15} aria-hidden="true" />
        返回告警列表
      </Link>

      <PageHeader
        eyebrow="Investigation report"
        title={alert.title}
        description={`告警 ID：${alertId ?? '—'}`}
        actions={<SeverityBadge severity={report.risk_level} />}
      />

      <div className="sf-report-meta">
        <span>
          状态 <StatusBadge status={alert.status} />
        </span>
        <span>创建于 {formatDateTime(alert.created_at)}</span>
        <span>事件数 {alert.event_count}</span>
        <span>证据数 {alert.evidence_count}</span>
        <span className="sf-mono" title={alert.rule_id}>
          {alert.rule_id} · v{alert.rule_version}
        </span>
      </div>

      {alert.status_history.length > 0 ? (
        <Card title="状态变更" subtitle="Status history">
          <ul className="sf-action-list">
            {alert.status_history.map((entry) => (
              <li key={`${entry.created_at}-${entry.to_status}`}>
                <Clock3 size={15} aria-hidden="true" />
                <span>
                  {entry.from_status ?? '—'} → {entry.to_status}
                  {entry.changed_by_username
                    ? ` · ${entry.changed_by_username}`
                    : ''}
                  {entry.reason ? ` · ${entry.reason}` : ''}
                </span>
                <span className="sf-muted">
                  {formatDateTime(entry.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <Card title="事件摘要" subtitle="Summary">
        <p className="sf-report-summary">{report.summary}</p>
      </Card>

      <Card
        title="证据事件"
        subtitle={
          truncated
            ? `${report.evidence.length} / ${report.evidence_total} 条 · 已截断，完整证据请使用证据分页接口`
            : `${report.evidence.length} 条 · 所有 event_id 均来自后端报告`
        }
      >
        <EvidenceTable evidence={report.evidence} />
      </Card>

      <div className="sf-report-grid">
        <Card title="事件时间线" subtitle="Timeline">
          <Timeline items={report.timeline} />
        </Card>

        <Card title="判断依据" subtitle="Reasoning">
          <div className="sf-prose">
            <p>{report.reasoning}</p>
          </div>
        </Card>
      </div>

      <div className="sf-report-grid">
        <Card
          title="推荐处置措施"
          subtitle="Recommended actions"
          actions={<ListChecks size={16} aria-hidden="true" />}
        >
          <ul className="sf-action-list">
            {report.recommended_actions.map((action) => (
              <li key={action}>
                <CheckCircle2 size={16} aria-hidden="true" />
                <span>{action}</span>
              </li>
            ))}
          </ul>
        </Card>

        <Card
          title="检测局限性"
          subtitle="Limitations"
          actions={<AlertTriangle size={16} aria-hidden="true" />}
        >
          <ul className="sf-limitation-list">
            {report.limitations.map((limitation) => (
              <li key={limitation}>
                <AlertTriangle size={15} aria-hidden="true" />
                <span>{limitation}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <InvestigationPanel alertId={alert.id} />

      {versions.length > 0 ? (
        <Card
          title="已保存的报告版本"
          subtitle={`${versions.length} 个版本`}
          actions={<History size={16} aria-hidden="true" />}
        >
          <ul className="sf-action-list">
            {versions.map((version) => (
              <li key={version.id}>
                <FileText size={15} aria-hidden="true" />
                <span>
                  v{version.version} ·{' '}
                  {REPORT_STATUS_LABELS[version.status] ?? version.status} ·{' '}
                  {version.generator}
                  {version.finalized_by_username
                    ? ` · 定稿人 ${version.finalized_by_username}`
                    : ''}
                </span>
                <span className="sf-muted">
                  {formatDateTime(version.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <footer className="sf-page-footnote">
        <FileText size={14} aria-hidden="true" />
        本页报告由后端按需生成，不会写入数据库；已保存的版本在上方单独列出。
        <Clock3 size={14} aria-hidden="true" />
        <span className="sf-mono" title={report.alert_id}>
          {shortId(report.alert_id)}
        </span>
      </footer>
    </div>
  )
}
