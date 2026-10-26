import { Inbox } from 'lucide-react'
import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  message?: string
  action?: ReactNode
}

export function EmptyState({ title, message, action }: EmptyStateProps) {
  return (
    <div className="sf-empty">
      <Inbox size={28} aria-hidden="true" />
      <h3>{title}</h3>
      {message ? <p>{message}</p> : null}
      {action ? <div className="sf-empty-action">{action}</div> : null}
    </div>
  )
}
