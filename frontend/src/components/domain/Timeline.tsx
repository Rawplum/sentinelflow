import type { ReportTimelineItem } from '../../api/types'
import { formatDateTime, shortId } from '../../lib/format'

export function Timeline({ items }: { items: ReportTimelineItem[] }) {
  if (items.length === 0) {
    return <div className="sf-table-empty">没有时间线数据</div>
  }

  return (
    <ol className="sf-timeline">
      {items.map((item) => (
        <li key={item.event_id} className="sf-timeline-item">
          <span className="sf-timeline-dot" aria-hidden="true" />
          <div className="sf-timeline-content">
            <time>{formatDateTime(item.timestamp)}</time>
            <p>{item.description}</p>
            <span className="sf-mono sf-muted" title={item.event_id}>
              {shortId(item.event_id)}
            </span>
          </div>
        </li>
      ))}
    </ol>
  )
}
