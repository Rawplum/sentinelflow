import type { ReactNode } from 'react'

interface CardProps {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = '',
}: CardProps) {
  const hasHeader = Boolean(title || subtitle || actions)

  return (
    <section className={`sf-card ${className}`.trim()}>
      {hasHeader ? (
        <header className="sf-card-header">
          <div>
            {title ? <h2 className="sf-card-title">{title}</h2> : null}
            {subtitle ? <p className="sf-card-subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="sf-card-actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className="sf-card-body">{children}</div>
    </section>
  )
}
