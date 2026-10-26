import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Clock, FileText, ShieldAlert } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { getAlert, getAlertEvidence } from '../api/alerts'
import { normalizeApiError } from '../api/errors'
import { InvestigationPanel } from '../components/domain/InvestigationPanel'
import { SeverityBadge, StatusBadge } from '../components/domain/Badges'
import { Card } from '../components/ui/Card'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { formatDateTime, shortId } from '../lib/format'

const EVIDENCE_PREVIEW = 10

/**
 * Alert detail: everything the backend knows about one alert, plus the entry
 * point for an investigation. All state comes from the API, so a refresh
 * rebuilds the page without any client-side hand-off.
 */
export function AlertDetailPage() {
  const { alertId = '' } = useParams()

  const alertQuery = useQuery({
    queryKey: ['alert', alertId],
    queryFn: () => getAlert(alertId),
    enabled: Boolean(alertId),
  })

  const evidenceQuery = useQuery({
    queryKey: ['alert-evidence', alertId],
    queryFn: () => getAlertEvidence(alertId, EVIDENCE_PREVIEW, 0),
    enabled: Boolean(alertId),
  })

  if (!alertId) {
    return <EmptyState title="缺少告警 ID" message="请从告警列表进入。" />
  }

  if (alertQuery.isLoading) {
    return <Spinner label="正在加载告警…" />
  }

  if (alertQuery.isError) {
    const error = normalizeApiError(alertQuery.error)
    if (error.status === 404) {
      return (
        <EmptyState
          title="告警不存在"
          message="该告警可能已被删除，或链接有误。"
        />
      )
    }
    return (
      <ErrorState
        message={`无法加载告警：${error.message}`}
        onRetry={() => void alertQuery.refetch()}
      />
    )
  }

  const alert = alertQuery.data
  if (!alert) {
    return <EmptyState title="没有告警数据" message="请从告警列表重新进入。" />
  }

  const evidence = evidenceQuery.data?.items ?? []
  const evidenceTotal = evidenceQuery.data?.total ?? alert.evidence_count

  return (
    <div className="sf-page">
      <header className="sf-page-header">
        <div>
          <p className="sf-eyebrow">Alert detail</p>
          <h1 className="sf-page-title">{alert.title}</h1>
          <p className="sf-page-subtitle">
            <span className="sf-mono">{alert.rule_id}</span> · v
            {alert.rule_version} · 告警 ID：<span className="sf-mono">{alert.id}</span>
          </p>
        </div>
        <div className="sf-page-header-actions">
          <SeverityBadge severity={alert.severity} />
          <StatusBadge status={alert.status} />
          <Link to={`/alerts/${alert.id}/report`} className="sf-btn sf-btn-secondary sf-btn-md">
            <FileText size={15} aria-hidden="true" />
            <span>查看报告</span>
          </Link>
        </div>
      </header>

      <Card title="告警信息" subtitle="Metadata" actions={<ShieldAlert size={16} aria-hidden="true" />}>
        <dl className="sf-investigation-meta">
          <div>
            <dt>首次出现</dt>
            <dd>{formatDateTime(alert.first_seen_at)}</dd>
          </div>
          <div>
            <dt>最近出现</dt>
            <dd>{formatDateTime(alert.last_seen_at)}</dd>
          </div>
          <div>
            <dt>事件数</dt>
            <dd>{alert.event_count}</dd>
          </div>
          <div>
            <dt>证据数</dt>
            <dd>{alert.evidence_count}</dd>
          </div>
          <div>
            <dt>创建时间</dt>
            <dd>{formatDateTime(alert.created_at)}</dd>
          </div>
          <div>
            <dt>告警 ID</dt>
            <dd className="sf-mono" title={alert.id}>
              {shortId(alert.id, 12)}
            </dd>
          </div>
        </dl>
        <p className="sf-muted">{alert.description}</p>
      </Card>

      <Card title="状态变更" subtitle="Status history" actions={<Clock size={16} aria-hidden="true" />}>
        {alert.status_history.length === 0 ? (
          <p className="sf-muted">该告警自创建以来没有状态变更。</p>
        ) : (
          <ul className="sf-action-list">
            {alert.status_history.map((entry) => (
              <li key={`${entry.created_at}-${entry.to_status}`}>
                <span>
                  {entry.from_status ?? '—'} → {entry.to_status} ·{' '}
                  {formatDateTime(entry.created_at)}
                  {entry.changed_by_username ? ` · ${entry.changed_by_username}` : ''}
                  {entry.reason ? ` · ${entry.reason}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card
        title="关联证据"
        subtitle={`显示前 ${Math.min(EVIDENCE_PREVIEW, evidenceTotal)} 条，共 ${evidenceTotal} 条`}
        actions={
          <Link
            to={`/alerts/${alert.id}/report`}
            className="sf-inline-link"
            aria-label="在报告中查看完整证据"
          >
            完整证据 <ArrowRight size={14} aria-hidden="true" />
          </Link>
        }
      >
        {evidenceQuery.isLoading ? (
          <Spinner label="加载证据…" />
        ) : evidenceQuery.isError ? (
          <ErrorState
            message="无法加载证据。"
            onRetry={() => void evidenceQuery.refetch()}
          />
        ) : evidence.length === 0 ? (
          <p className="sf-muted">该告警没有关联证据事件。</p>
        ) : (
          <div className="sf-table-wrap">
            <table className="sf-table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>事件 ID</th>
                  <th>用户 / IP</th>
                  <th>操作</th>
                  <th>结果</th>
                </tr>
              </thead>
              <tbody>
                {evidence.map((event) => (
                  <tr key={event.event_id}>
                    <td>{formatDateTime(event.timestamp)}</td>
                    <td className="sf-mono" title={event.event_id}>
                      {shortId(event.event_id, 12)}
                    </td>
                    <td>
                      {event.username ?? '—'}
                      <br />
                      <span className="sf-mono sf-muted">{event.source_ip ?? '—'}</span>
                    </td>
                    <td>{event.action}</td>
                    <td>{event.outcome}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <InvestigationPanel alertId={alert.id} />

      <footer className="sf-page-footnote">
        本页所有数据来自 <code>GET /api/v1/alerts/&lt;id&gt;</code> 与{' '}
        <code>/evidence</code>，刷新后可直接重建；不依赖列表页传入的状态。
      </footer>
    </div>
  )
}
