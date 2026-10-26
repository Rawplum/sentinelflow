import { formatJson } from '../../lib/format'

export function AuditDetails({
  details,
}: {
  details: Record<string, unknown> | null
}) {
  if (!details || Object.keys(details).length === 0) {
    return <span className="sf-muted">—</span>
  }

  return (
    <details className="sf-audit-details">
      <summary>查看详情</summary>
      <pre className="sf-json">{formatJson(details)}</pre>
    </details>
  )
}
