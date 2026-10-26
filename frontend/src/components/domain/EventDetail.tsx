import type { SecurityEvent } from '../../api/types'
import { formatDateTime, formatNullable } from '../../lib/format'

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="sf-detail-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  )
}

export function EventDetail({ event }: { event: SecurityEvent }) {
  return (
    <div className="sf-stack">
      <dl className="sf-detail-grid">
        <DetailRow label="事件 ID" value={event.event_id} />
        <DetailRow label="发生时间" value={formatDateTime(event.timestamp)} />
        <DetailRow label="事件类型" value={event.event_type} />
        <DetailRow label="用户名" value={formatNullable(event.username)} />
        <DetailRow label="来源 IP" value={formatNullable(event.source_ip)} />
        <DetailRow label="资产" value={formatNullable(event.asset_id)} />
        <DetailRow label="操作" value={event.action} />
        <DetailRow label="结果" value={event.outcome} />
        <DetailRow label="来源" value={event.source} />
        <DetailRow label="入库时间" value={formatDateTime(event.created_at)} />
      </dl>
      <div>
        <h3 className="sf-section-label">原始消息</h3>
        <pre className="sf-raw-message">{event.raw_message}</pre>
      </div>
    </div>
  )
}
