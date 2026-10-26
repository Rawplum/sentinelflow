import type { ReactNode } from 'react'

export type BadgeTone =
  | 'neutral'
  | 'accent'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info'
  | 'muted'
  | 'purple'

interface BadgeProps {
  tone?: BadgeTone
  children: ReactNode
  className?: string
}

export function Badge({ tone = 'neutral', children, className = '' }: BadgeProps) {
  return (
    <span className={`sf-badge sf-badge-${tone} ${className}`.trim()}>
      {children}
    </span>
  )
}
