import { useQuery } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { listAuditLogs } from '../api/audit'
import type { AuditLog } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { AuditDetails } from '../components/domain/AuditDetails'
import { OutcomeBadge } from '../components/domain/Badges'
import { PageHeader } from '../components/layout/PageHeader'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import type { Column } from '../components/ui/DataTable'
import { ErrorState } from '../components/ui/ErrorState'
import { Pagination } from '../components/ui/Pagination'
import { Spinner } from '../components/ui/Spinner'
import { usePagination } from '../hooks/usePagination'
import { AUDIT_ACTIONS } from '../lib/constants'
import {
  formatAuditAction,
  formatDateTime,
  formatNullable,
  shortId,
} from '../lib/format'
import { ForbiddenPage } from './ForbiddenPage'

export function AuditPage() {
  const { isAdmin } = useAuth()
  const { limit, offset, setLimit, setOffset } = usePagination()
  const [searchParams, setSearchParams] = useSearchParams()
  const action = searchParams.get('action') ?? ''

  const query = useQuery({
    queryKey: ['audit', limit, offset, action],
    queryFn: () => listAuditLogs(limit, offset, action || undefined),
    enabled: isAdmin,
  })

  if (!isAdmin) {
    return <ForbiddenPage />
  }

  const handleActionChange = (nextAction: string) => {
    const params = new URLSearchParams(searchParams)
    if (nextAction) {
      params.set('action', nextAction)
    } else {
      params.delete('action')
    }
    params.delete('offset')
    setSearchParams(params, { replace: true })
  }

  const columns: Column<AuditLog>[] = [
    {
      key: 'time',
      header: '时间',
      render: (entry) => formatDateTime(entry.created_at),
      width: '180px',
    },
    {
      key: 'actor',
      header: '操作者',
      render: (entry) => (
        <div className="sf-table-primary">
          <span>{formatNullable(entry.actor_username)}</span>
          <span className="sf-mono sf-muted sf-table-subtext" title={entry.actor_user_id ?? undefined}>
            {entry.actor_user_id ? shortId(entry.actor_user_id, 8) : '—'}
          </span>
        </div>
      ),
      width: '150px',
    },
    {
      key: 'action',
      header: '操作',
      render: (entry) => (
        <div className="sf-table-primary">
          <span>{formatAuditAction(entry.action)}</span>
          <span className="sf-mono sf-muted sf-table-subtext">{entry.action}</span>
        </div>
      ),
      width: '180px',
    },
    {
      key: 'outcome',
      header: '结果',
      render: (entry) => <OutcomeBadge outcome={entry.outcome} />,
      width: '90px',
    },
    {
      key: 'resource',
      header: '资源',
      render: (entry) => (
        <span className="sf-mono" title={entry.resource_id ?? undefined}>
          {entry.resource_type ?? '—'}
          {entry.resource_id ? ` · ${shortId(entry.resource_id, 8)}` : ''}
        </span>
      ),
      width: '160px',
    },
    {
      key: 'ip',
      header: '来源 IP',
      render: (entry) => (
        <span className="sf-mono">{formatNullable(entry.source_ip)}</span>
      ),
      width: '130px',
    },
    {
      key: 'request',
      header: '请求 ID',
      render: (entry) => (
        <span className="sf-mono sf-muted" title={entry.request_id ?? undefined}>
          {entry.request_id ? shortId(entry.request_id, 12) : '—'}
        </span>
      ),
      width: '150px',
    },
    {
      key: 'details',
      header: '详情',
      render: (entry) => <AuditDetails details={entry.details} />,
      width: '110px',
    },
  ]

  return (
    <div className="sf-page">
      <PageHeader
        eyebrow="Governance"
        title="操作审计"
        description="只读审计记录。登录、导入、检测、报告查看和权限拒绝都会记录。"
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

      <div className="sf-toolbar">
        <label className="sf-inline-field">
          <span>操作类型</span>
          <select
            className="sf-select"
            value={action}
            onChange={(event) => handleActionChange(event.target.value)}
          >
            <option value="">全部操作</option>
            {AUDIT_ACTIONS.map((item) => (
              <option key={item} value={item}>
                {formatAuditAction(item)} ({item})
              </option>
            ))}
          </select>
        </label>
        <span className="sf-muted">
          查看审计页本身会产生一条 <span className="sf-mono">audit.view</span> 记录。
        </span>
      </div>

      <Card
        title="审计日志"
        subtitle={
          query.data
            ? `共 ${query.data.total} 条，当前显示 ${query.data.items.length} 条`
            : '加载中'
        }
      >
        {query.isLoading ? (
          <Spinner label="加载审计记录…" />
        ) : query.isError ? (
          <ErrorState
            message="无法加载审计记录。"
            onRetry={() => void query.refetch()}
          />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={query.data?.items ?? []}
              rowKey={(entry) => entry.id}
              emptyMessage="当前过滤条件下没有审计记录。"
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
        后端仅支持 action 精确过滤；时间范围和操作者过滤尚未实现。
      </footer>
    </div>
  )
}
