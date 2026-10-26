import { SEVERITY_LABELS, STATUS_LABELS, OUTCOME_LABELS, ROLE_LABELS } from '../../lib/constants'

function normalize(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9_-]/g, '')
}

export function SeverityBadge({ severity }: { severity: string }) {
  const normalized = normalize(severity)
  return (
    <span className={`sf-badge sf-severity-${normalized}`}>
      {SEVERITY_LABELS[normalized] ?? severity}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const normalized = normalize(status)
  return (
    <span className={`sf-badge sf-status-${normalized}`}>
      {STATUS_LABELS[normalized] ?? status}
    </span>
  )
}

export function OutcomeBadge({ outcome }: { outcome: string }) {
  const normalized = normalize(outcome)
  return (
    <span className={`sf-badge sf-outcome-${normalized}`}>
      {OUTCOME_LABELS[normalized] ?? outcome}
    </span>
  )
}

export function RoleBadge({ role }: { role?: string | null }) {
  const normalized = normalize(role ?? '')
  return (
    <span className={`sf-badge sf-role-${normalized || 'unknown'}`}>
      {ROLE_LABELS[normalized] ?? role ?? '未知角色'}
    </span>
  )
}
