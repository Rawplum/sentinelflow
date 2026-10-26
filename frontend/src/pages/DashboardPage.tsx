import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  Bell,
  FileText,
  Radar,
  ShieldAlert,
  ShieldCheck,
  Upload,
} from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { listAlerts } from '../api/alerts'
import { listAuditLogs } from '../api/audit'
import { listEvents } from '../api/events'
import type { Alert, AuditLog } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { ImportEventsModal } from '../components/domain/ImportEventsModal'
import { RunDetectionButton } from '../components/domain/RunDetectionButton'
import { OutcomeBadge, SeverityBadge, StatusBadge } from '../components/domain/Badges'
import { PageHeader } from '../components/layout/PageHeader'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import type { Column } from '../components/ui/DataTable'
import { EmptyState } from '../components/ui/EmptyState'
import { ErrorState } from '../components/ui/ErrorState'
import { Spinner } from '../components/ui/Spinner'
import { SEVERITY_LABELS, SEVERITY_ORDER } from '../lib/constants'
import { formatDateTime, formatNumber, formatPercent } from '../lib/format'

function detectionCreatedCount(details: Record<string, unknown> | null): number | null {
  if (!details) return null
  const value = details.alerts_created
  return typeof value === 'number' ? value : null
}

export function DashboardPage() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const [importOpen, setImportOpen] = useState(false)

  const eventsQuery = useQuery({
    queryKey: ['dashboard', 'events'],
    queryFn: () => listEvents(5, 0),
  })

  const alertsQuery = useQuery({
    queryKey: ['dashboard', 'alerts'],
    queryFn: () => listAlerts(100, 0),
  })

  const recentAuditQuery = useQuery({
    queryKey: ['dashboard', 'audit-recent'],
    queryFn: () => listAuditLogs(5, 0),
    enabled: isAdmin,
  })

  const lastDetectionQuery = useQuery({
    queryKey: ['dashboard', 'detection-last'],
    queryFn: () => listAuditLogs(1, 0, 'detections.run'),
    enabled: isAdmin,
  })

  const alerts = alertsQuery.data?.items ?? []
  const totalAlerts = alertsQuery.data?.total ?? 0
  const totalEvents = eventsQuery.data?.total ?? 0
  const sampleSize = alerts.length
  const highCriticalCount = alerts.filter(
    (alert) => alert.severity === 'critical' || alert.severity === 'high',
  ).length
  const severityCounts = SEVERITY_ORDER.map((severity) => ({
    severity,
    count: alerts.filter((alert) => alert.severity === severity).length,
  }))
  const lastDetection = lastDetectionQuery.data?.items[0] ?? null
  const createdCount = lastDetection
    ? detectionCreatedCount(lastDetection.details)
    : null

  const alertColumns: Column<Alert>[] = [
    {
      key: 'severity',
      header: '严重性',
      render: (alert) => <SeverityBadge severity={alert.severity} />,
      width: '88px',
    },
    {
      key: 'title',
      header: '告警',
      render: (alert) => (
        <div className="sf-table-primary">
          <Link
            to={`/alerts/${alert.id}/report`}
            state={{ alert }}
            className="sf-inline-link"
          >
            {alert.title}
          </Link>
          <span className="sf-muted sf-table-subtext">
            {alert.rule_id} · {alert.rule_version}
          </span>
        </div>
      ),
    },
    {
      key: 'status',
      header: '状态',
      render: (alert) => <StatusBadge status={alert.status} />,
      width: '104px',
    },
    {
      key: 'created',
      header: '创建时间',
      render: (alert) => formatDateTime(alert.created_at),
      width: '190px',
    },
  ]

  const recentAlerts = alerts.slice(0, 5)

  return (
    <div className="sf-page">
      <PageHeader
        eyebrow="Overview"
        title="安全运营仪表盘"
        description="基于后端真实数据的事件、告警与检测概览。"
        actions={
          isAdmin ? (
            <Button
              variant="primary"
              icon={<Upload size={15} aria-hidden="true" />}
              onClick={() => setImportOpen(true)}
            >
              导入事件
            </Button>
          ) : undefined
        }
      />

      <section className="sf-kpi-grid" aria-label="关键指标">
        <div className="sf-kpi">
          <div className="sf-kpi-icon">
            <ShieldAlert size={18} aria-hidden="true" />
          </div>
          <span className="sf-kpi-label">事件总量</span>
          <strong className="sf-kpi-value">
            {eventsQuery.isLoading ? '—' : formatNumber(totalEvents)}
          </strong>
          <span className="sf-kpi-hint">全部已导入安全事件</span>
        </div>
        <div className="sf-kpi">
          <div className="sf-kpi-icon">
            <Bell size={18} aria-hidden="true" />
          </div>
          <span className="sf-kpi-label">告警总量</span>
          <strong className="sf-kpi-value">
            {alertsQuery.isLoading ? '—' : formatNumber(totalAlerts)}
          </strong>
          <span className="sf-kpi-hint">AUTH-001 生成的告警</span>
        </div>
        <div className="sf-kpi">
          <div className="sf-kpi-icon">
            <Radar size={18} aria-hidden="true" />
          </div>
          <span className="sf-kpi-label">高/严重告警</span>
          <strong className="sf-kpi-value">
            {alertsQuery.isLoading ? '—' : formatNumber(highCriticalCount)}
          </strong>
          <span className="sf-kpi-hint">
            最近样本 {formatNumber(sampleSize)} / {formatNumber(totalAlerts)} 条
          </span>
        </div>
        <div className="sf-kpi">
          <div className="sf-kpi-icon">
            <ShieldCheck size={18} aria-hidden="true" />
          </div>
          <span className="sf-kpi-label">最近检测</span>
          <strong className="sf-kpi-value sf-kpi-value-small">
            {!isAdmin
              ? '仅管理员'
              : lastDetectionQuery.isLoading
                ? '…'
                : lastDetection
                  ? formatDateTime(lastDetection.created_at)
                  : '暂无记录'}
          </strong>
          <span className="sf-kpi-hint">
            {!isAdmin
              ? '检测运行历史仅管理员可查看'
              : lastDetection
                ? `创建 ${createdCount ?? 0} 个告警`
                : '尚未从审计记录中发现检测运行'}
          </span>
        </div>
      </section>

      <div className="sf-dashboard-grid">
        <Card
          title="告警严重性分布"
          subtitle={
            totalAlerts > sampleSize
              ? `基于最近 ${sampleSize} 条告警的样本，不代表全量分布`
              : '基于当前已加载告警'
          }
        >
          {alertsQuery.isLoading ? (
            <Spinner label="加载告警分布…" />
          ) : alertsQuery.isError ? (
            <ErrorState
              message="无法加载告警分布。"
              onRetry={() => void alertsQuery.refetch()}
            />
          ) : sampleSize === 0 ? (
            <EmptyState title="暂无告警" message="运行检测后，这里会显示严重性分布。" />
          ) : (
            <div className="sf-distribution">
              {severityCounts.map(({ severity, count }) => (
                <div key={severity} className="sf-distribution-row">
                  <span className="sf-distribution-label">
                    {SEVERITY_LABELS[severity] ?? severity}
                  </span>
                  <div className="sf-distribution-track">
                    <span
                      className={`sf-distribution-bar sf-severity-bar-${severity}`}
                      style={{ width: `${(count / sampleSize) * 100}%` }}
                    />
                  </div>
                  <span className="sf-distribution-value">
                    {count} · {formatPercent(count, sampleSize)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card
          title="管理员操作"
          subtitle="仅管理员可见；后端仍会强制校验角色。"
        >
          {isAdmin ? (
            <div className="sf-stack">
              <div className="sf-action-row">
                <Button
                  variant="secondary"
                  icon={<Upload size={15} aria-hidden="true" />}
                  onClick={() => setImportOpen(true)}
                >
                  导入合成事件
                </Button>
                <RunDetectionButton />
              </div>
              <Link to="/audit" className="sf-inline-link">
                查看操作审计 <ArrowRight size={14} aria-hidden="true" />
              </Link>
            </div>
          ) : (
            <div className="sf-alert sf-alert-info">
              当前为分析员只读视图。导入、检测和审计接口由后端返回 403。
            </div>
          )}
        </Card>

        <Card
          title="最近告警"
          subtitle="最新 5 条"
          actions={
            <Link to="/alerts" className="sf-inline-link">
              查看全部 <ArrowRight size={14} aria-hidden="true" />
            </Link>
          }
          className="sf-span-2"
        >
          {alertsQuery.isLoading ? (
            <Spinner label="加载告警…" />
          ) : alertsQuery.isError ? (
            <ErrorState
              message="无法加载告警列表。"
              onRetry={() => void alertsQuery.refetch()}
            />
          ) : recentAlerts.length === 0 ? (
            <EmptyState
              title="暂无告警"
              message={
                isAdmin
                  ? '导入事件并运行检测后，这里会出现告警。'
                  : '当前没有可查看的告警。'
              }
            />
          ) : (
            <DataTable
              columns={alertColumns}
              rows={recentAlerts}
              rowKey={(alert) => alert.id}
              onRowClick={(alert) =>
                navigate(`/alerts/${alert.id}/report`, { state: { alert } })
              }
            />
          )}
        </Card>

        <Card
          title="最近事件"
          subtitle="最新 5 条"
          actions={
            <Link to="/events" className="sf-inline-link">
              查看全部 <ArrowRight size={14} aria-hidden="true" />
            </Link>
          }
        >
          {eventsQuery.isLoading ? (
            <Spinner label="加载事件…" />
          ) : eventsQuery.isError ? (
            <ErrorState
              message="无法加载事件列表。"
              onRetry={() => void eventsQuery.refetch()}
            />
          ) : (eventsQuery.data?.items.length ?? 0) === 0 ? (
            <EmptyState title="暂无事件" message="导入合成日志后会显示最近事件。" />
          ) : (
            <ul className="sf-activity-list">
              {eventsQuery.data?.items.map((event) => (
                <li key={event.event_id}>
                  <div className="sf-activity-main">
                    <span className="sf-activity-title">
                      {event.event_type}
                    </span>
                    <span className="sf-muted">
                      {event.username ?? '未知用户'} · {event.source_ip ?? '未知 IP'}
                    </span>
                  </div>
                  <div className="sf-activity-meta">
                    <OutcomeBadge outcome={event.outcome} />
                    <time>{formatDateTime(event.timestamp)}</time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card
          title="最近审计"
          subtitle={isAdmin ? '最新 5 条' : '仅管理员可见'}
          actions={
            isAdmin ? (
              <Link to="/audit" className="sf-inline-link">
                审计页 <ArrowRight size={14} aria-hidden="true" />
              </Link>
            ) : undefined
          }
        >
          {!isAdmin ? (
            <EmptyState
              title="审计仅管理员可见"
              message="分析员没有 audit:read 权限。"
            />
          ) : recentAuditQuery.isLoading ? (
            <Spinner label="加载审计…" />
          ) : recentAuditQuery.isError ? (
            <ErrorState
              message="无法加载审计记录。"
              onRetry={() => void recentAuditQuery.refetch()}
            />
          ) : (recentAuditQuery.data?.items.length ?? 0) === 0 ? (
            <EmptyState title="暂无审计记录" message="登录和操作后会产生审计记录。" />
          ) : (
            <ul className="sf-activity-list">
              {recentAuditQuery.data?.items.map((entry: AuditLog) => (
                <li key={entry.id}>
                  <div className="sf-activity-main">
                    <span className="sf-activity-title">{entry.action}</span>
                    <span className="sf-muted">
                      {entry.actor_username ?? '系统/未知'}
                    </span>
                  </div>
                  <div className="sf-activity-meta">
                    <OutcomeBadge outcome={entry.outcome} />
                    <time>{formatDateTime(entry.created_at)}</time>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <footer className="sf-page-footnote">
        <FileText size={14} aria-hidden="true" />
        仪表盘不伪造全局统计：严重性分布基于已加载样本，并明确标注样本范围。
      </footer>

      <ImportEventsModal open={importOpen} onClose={() => setImportOpen(false)} />
    </div>
  )
}
