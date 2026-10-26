import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'

import { server } from './msw/server'

beforeAll(() => {
  server.listen()
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
  sessionStorage.clear()
})

afterAll(() => {
  server.close()
})
