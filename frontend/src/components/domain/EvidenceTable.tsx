import { ChevronDown, ChevronUp } from 'lucide-react'
import { Fragment, useState } from 'react'

import type { ReportEvidence } from '../../api/types'
import { formatDateTime, formatNullable, shortId } from '../../lib/format'
import { OutcomeBadge } from './Badges'

export function EvidenceTable({ evidence }: { evidence: ReportEvidence[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null)

  if (evidence.length === 0) {
    return <div className="sf-table-empty">没有关联证据事件</div>
  }

  return (
    <div className="sf-table-wrap">
      <table className="sf-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>事件 ID</th>
            <th>用户 / IP</th>
            <th>资产</th>
            <th>操作</th>
            <th>结果</th>
            <th>原始消息</th>
          </tr>
        </thead>
        <tbody>
          {evidence.map((item) => {
            const expanded = expandedId === item.event_id
            return (
              <Fragment key={item.event_id}>
                <tr>
                  <td>{formatDateTime(item.timestamp)}</td>
                  <td>
                    <span className="sf-mono" title={item.event_id}>
                      {shortId(item.event_id)}
                    </span>
                  </td>
                  <td>
                    <div>{formatNullable(item.username)}</div>
                    <div className="sf-muted sf-mono">
                      {formatNullable(item.source_ip)}
                    </div>
                  </td>
                  <td>{formatNullable(item.asset_id)}</td>
                  <td>{item.action}</td>
                  <td>
                    <OutcomeBadge outcome={item.outcome} />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="sf-link-button"
                      onClick={() =>
                        setExpandedId(expanded ? null : item.event_id)
                      }
                      aria-expanded={expanded}
                    >
                      {expanded ? (
                        <ChevronUp size={14} />
                      ) : (
                        <ChevronDown size={14} />
                      )}
                      {expanded ? '收起' : '查看'}
                    </button>
                  </td>
                </tr>
                {expanded ? (
                  <tr className="sf-evidence-expanded">
                    <td colSpan={7}>
                      <pre className="sf-raw-message">
                        {item.raw_message ?? '（本次响应未包含原始消息）'}
                      </pre>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
