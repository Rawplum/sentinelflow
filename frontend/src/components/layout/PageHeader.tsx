import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  description?: string
  actions?: ReactNode
  eyebrow?: string
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: PageHeaderProps) {
  return (
    <header className="sf-page-header">
      <div>
        {eyebrow ? <p className="sf-eyebrow">{eyebrow}</p> : null}
        <h1 className="sf-page-title">{title}</h1>
        {description ? <p className="sf-page-description">{description}</p> : null}
      </div>
      {actions ? <div className="sf-page-actions">{actions}</div> : null}
    </header>
  )
}
