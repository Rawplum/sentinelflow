import { ChevronLeft, ChevronRight } from 'lucide-react'

import { PAGE_SIZES } from '../../lib/constants'
import { formatNumber } from '../../lib/format'

interface PaginationProps {
  total: number
  limit: number
  offset: number
  onOffsetChange: (offset: number) => void
  onLimitChange: (limit: number) => void
}

export function Pagination({
  total,
  limit,
  offset,
  onOffsetChange,
  onLimitChange,
}: PaginationProps) {
  const page = Math.floor(offset / limit) + 1
  const totalPages = Math.max(1, Math.ceil(total / limit))
  const start = total === 0 ? 0 : offset + 1
  const end = Math.min(offset + limit, total)

  return (
    <div className="sf-pagination">
      <div className="sf-pagination-summary">
        显示 <strong>{formatNumber(start)}</strong>–<strong>{formatNumber(end)}</strong>{' '}
        / 共 <strong>{formatNumber(total)}</strong> 条
      </div>
      <div className="sf-pagination-controls">
        <label className="sf-page-size">
          每页
          <select
            aria-label="每页条数"
            value={limit}
            onChange={(event) => onLimitChange(Number(event.target.value))}
          >
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <span className="sf-page-number">
          第 {page} / {totalPages} 页
        </span>
        <button
          type="button"
          className="sf-page-btn"
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
          aria-label="上一页"
        >
          <ChevronLeft size={16} />
        </button>
        <button
          type="button"
          className="sf-page-btn"
          onClick={() => onOffsetChange(offset + limit)}
          disabled={end >= total}
          aria-label="下一页"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  )
}
