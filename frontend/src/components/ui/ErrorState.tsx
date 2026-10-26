import { AlertTriangle } from 'lucide-react'

import { Button } from './Button'

interface ErrorStateProps {
  message: string
  onRetry?: () => void
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div className="sf-error-state" role="alert">
      <AlertTriangle size={26} aria-hidden="true" />
      <div>
        <h3>请求失败</h3>
        <p>{message}</p>
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          重试
        </Button>
      ) : null}
    </div>
  )
}
