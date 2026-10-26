import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Upload } from 'lucide-react'
import { useState } from 'react'

import { listEvents } from '../api/events'
import type { SecurityEvent } from '../api/types'
import { useAuth } from '../auth/useAuth'
import { OutcomeBadge } from '../components/domain/Badges'
import { EventDetail } from '../components/domain/EventDetail'
import { ImportEventsModal } from '../components/domain/ImportEventsModal'
import { PageHeader } from '../components/layout/PageHeader'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'
import { DataTable } from '../components/ui/DataTable'
import type { Column } from '../components/ui/DataTable'
import { Drawer } from '../components/ui/Drawer'
import { ErrorState } from '../components/ui/ErrorState'
import { Pagination } from '../components/ui/Pagination'
import { Spinner } from '../components/ui/Spinner'
import { usePagination } from '../hooks/usePagination'
import { formatDateTime, formatNullable } from '../lib/format'

export function EventsPage() {
  const { isAdmin } = useAuth()
  const { limit, offset, setLimit, setOffset } = usePagination()
  const [selected, setSelected] = useState<SecurityEvent | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  const query = useQuery({
    queryKey: ['events', limit, offset],
    queryFn: () => listEvents(limit, offset),
  })

  const columns: Column<SecurityEvent>[] = [
    {
      key: 'timestamp',
      header: '时间',
      render: (event) => formatDateTime(event.timestamp),
      width: '180px',
    },
    {
      key: 'type',
      header: '类型',
      render: (event) => <span className="sf-mono">{event.event_type}</span>,
    },
    {
      key: 'user',
      header: '用户',
      render: (event) => formatNullable(event.username),
    },
    {
      key: 'ip',
      header: '来源 IP',
      render: (event) => (
        <span className="sf-mono">{formatNullable(event.source_ip)}</span>
      ),
    },
    {
      key: 'asset',
      header: '资产',
      render: (event) => formatNullable(event.asset_id),
    },
    {
      key: 'action',
      header: '操作',
      render: (event) => event.action,
    },
    {
      key: 'outcome',
      header: '结果',
      render: (event) => <OutcomeBadge outcome={event.outcome} />,
      width: '92px',
    },
    {
      key: 'source',
      header: '来源',
      render: (event) => event.source,
    },
  ]

  return (
    <div className="sf-page">
      <PageHeader
        eyebrow="Telemetry"
        title="安全事件"
        description="查看已导入的安全事件。后端当前仅支持 limit / offset 分页，不支持字段过滤。"
        actions={
          <>
            <Button
              variant="ghost"
              icon={<RefreshCw size={15} aria-hidden="true" />}
              loading={query.isFetching}
              onClick={() => void query.refetch()}
            >
              刷新
            </Button>
            {isAdmin ? (
              <Button
                variant="primary"
                icon={<Upload size={15} aria-hidden="true" />}
                onClick={() => setImportOpen(true)}
              >
                导入事件
              </Button>
            ) : null}
          </>
        }
      />

      <Card
        title="事件记录"
        subtitle={
          query.data
            ? `共 ${query.data.total} 条，当前显示 ${query.data.items.length} 条`
            : '加载中'
        }
      >
        {query.isLoading ? (
          <Spinner label="加载事件…" />
        ) : query.isError ? (
          <ErrorState
            message="无法加载事件列表。"
            onRetry={() => void query.refetch()}
          />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={query.data?.items ?? []}
              rowKey={(event) => event.event_id}
              onRowClick={setSelected}
              emptyMessage={
                isAdmin
                  ? '暂无事件。可以导入合成安全日志后查看。'
                  : '暂无事件。'
              }
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
        事件 ID 与原始消息只在详情抽屉中展示；页面不会解析或改写原始日志。
      </footer>

      <Drawer
        open={selected !== null}
        title="事件详情"
        onClose={() => setSelected(null)}
      >
        {selected ? <EventDetail event={selected} /> : null}
      </Drawer>

      <ImportEventsModal open={importOpen} onClose={() => setImportOpen(false)} />
    </div>
  )
}
