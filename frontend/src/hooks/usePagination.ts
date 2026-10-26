import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

import { DEFAULT_PAGE_SIZE, PAGE_SIZES } from '../lib/constants'

export interface PaginationState {
  limit: number
  offset: number
  setLimit: (limit: number) => void
  setOffset: (offset: number) => void
}

export function usePagination(): PaginationState {
  const [searchParams, setSearchParams] = useSearchParams()

  const parsedLimit = Number(searchParams.get('limit'))
  const limit = PAGE_SIZES.includes(parsedLimit)
    ? parsedLimit
    : DEFAULT_PAGE_SIZE

  const parsedOffset = Number(searchParams.get('offset'))
  const offset =
    Number.isFinite(parsedOffset) && parsedOffset >= 0
      ? Math.floor(parsedOffset)
      : 0

  const update = useCallback(
    (nextLimit: number, nextOffset: number) => {
      const params = new URLSearchParams(searchParams)
      params.set('limit', String(nextLimit))
      if (nextOffset > 0) {
        params.set('offset', String(nextOffset))
      } else {
        params.delete('offset')
      }
      setSearchParams(params, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  const setLimit = useCallback(
    (nextLimit: number) => {
      update(nextLimit, 0)
    },
    [update],
  )

  const setOffset = useCallback(
    (nextOffset: number) => {
      update(limit, Math.max(0, nextOffset))
    },
    [limit, update],
  )

  return { limit, offset, setLimit, setOffset }
}
