import { LoaderCircle } from 'lucide-react'

interface SpinnerProps {
  label?: string
  size?: number
}

export function Spinner({ label, size = 18 }: SpinnerProps) {
  return (
    <span className="sf-spinner" role="status" aria-live="polite">
      <LoaderCircle size={size} className="sf-spin" aria-hidden="true" />
      {label ? <span>{label}</span> : null}
    </span>
  )
}
