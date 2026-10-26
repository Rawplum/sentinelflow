import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'

import { listAlerts } from '../api/alerts'
import type { Alert } from '../api/types'
import { useAuth } from '../auth/useAuth'
import {
  SeverityBadge,
  StatusBadge,
} from '../components/domain/Badges'
import { RunDetectionButton } from '../components/domain/RunDetectionButton'
import { PageHeader } from '../components/layout/PageHeader'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import type { Column } from '../components/ui/DataTable'
import { ErrorState } from '../components/ui/ErrorState'
import { Pagination } from '../components/ui/Pagination'
import { Spinner } from '../components/ui/Spinner'
import { usePagination } from '../hooks/usePagination'
import { formatDateTime, formatNumber } from '../lib/format'

export function AlertsPage() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const { limit, offset, setLimit, setOffset } = usePagination()

  const query = useQuery({
    queryKey: ['alerts', limit, offset],
    queryFn: () => listAlerts(limit, offset),
  })

  const openReport = (alert: Alert) => {
    navigate(`/alerts/${alert.id}/report`)
  }

  const columns: Column<Alert>[] = [
    {
      key: 'severity',
      header: '严重性',
      render: (alert) => <SeverityBadge severity={alert.severity} />,
      width: '88px',
    },
    {
      key: 'status',
      header: '状态',
      render: (alert) => <StatusBadge status={alert.status} />,
      width: '100px',
    },
    {
      key: 'title',
      header: '告警',
      render: (alert) => (
        <div className="sf-table-primary">
          <Link
            to={`/alerts/${alert.id}/report`}
            className="sf-inline-link"
            onClick={(event) => event.stopPropagation()}
          >
            {alert.title}
          </Link>
          <span className="sf-muted sf-table-subtext" title={alert.description}>
            {alert.description}
          </span>
          <span className="sf-mono sf-muted sf-table-subtext">
            {alert.rule_id} · v{alert.rule_version}
          </span>
        </div>
      ),
    },
    {
      key: 'events',
      header: '事件',
      render: (alert) => formatNumber(alert.event_count),
      width: '72px',
    },
    {
      key: 'evidence',
      header: '证据',
      render: (alert) => formatNumber(alert.evidence_count),
      width: '72px',
    },
    {
      key: 'first_seen',
      header: '首次发现',
      render: (alert) => formatDateTime(alert.first_seen_at),
      width: '170px',
    },
    {
      key: 'last_seen',
      header: '最近发现',
      render: (alert) => formatDateTime(alert.last_seen_at),
      width: '170px',
    },
    {
      key: 'report',
      header: '',
      render: (alert) => (
        <Link
          to={`/alerts/${alert.id}/report`}
          className="sf-link-button"
          onClick={(event) => event.stopPropagation()}
        >
          查看报告
        </Link>
      ),
      width: '96px',
    },
  ]

  return (
    <div className="sf-page">
      <PageHeader
        eyebrow="Detection"
        title="告警"
        description="AUTH-001 生成的告警与证据数量。点击告警查看调查报告。"
        actions={
          <Button
            variant="ghost"
            icon={<RefreshCw size={15} aria-hidden="true" />}
            loading={query.isFetching}
            onClick={() => void query.refetch()}
          >
            刷新
          </Button>
        }
      />

      {isAdmin ? (
        <div className="sf-toolbar sf-toolbar-between">
          <div>
            <span className="sf-toolbar-label">检测操作</span>
            <span className="sf-muted">
              运行确定性 AUTH-001 规则；重复运行不会创建重复告警。
            </span>
          </div>
          <RunDetectionButton />
        </div>
      ) : (
        <div className="sf-alert sf-alert-info">
          当前为分析员只读视图。运行检测需要管理员权限，后端会拒绝越权请求。
        </div>
      )}

      <Card
        title="告警队列"
        subtitle={
          query.data
            ? `共 ${formatNumber(query.data.total)} 条，当前显示 ${formatNumber(query.data.items.length)} 条`
            : '加载中'
        }
      >
        {query.isLoading ? (
          <Spinner label="加载告警…" />
        ) : query.isError ? (
          <ErrorState
            message="无法加载告警列表。"
            onRetry={() => void query.refetch()}
          />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={query.data?.items ?? []}
              rowKey={(alert) => alert.id}
              onRowClick={openReport}
              emptyMessage="暂无告警。导入事件并运行检测后会出现结果。"
            />
            <Pagination
              total={query.data?.total ?? 0}
              limit={limit}
              offset={offset}
              onLimitChange={setLimit}
              onOffsetChange={setOffset}
            />
          </>
        )}
      </Card>

      <footer className="sf-page-footnote">
        告警状态修改由后端 PATCH /api/v1/alerts/&lt;id&gt; 提供（仅管理员）；当前页面不提供状态操作按钮，状态变更请通过 API 完成。
      </footer>
    </div>
  )
}
