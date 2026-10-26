const SESSION_KEY = 'sentinelflow.session'

export interface StoredSession {
  accessToken: string
  expiresAt: number
}

export function readSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return null
    const candidate = parsed as Record<string, unknown>
    if (
      typeof candidate.accessToken !== 'string' ||
      typeof candidate.expiresAt !== 'number'
    ) {
      return null
    }
    return {
      accessToken: candidate.accessToken,
      expiresAt: candidate.expiresAt,
    }
  } catch {
    return null
  }
}

export function writeSession(session: StoredSession): void {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
  } catch {
    // sessionStorage can be unavailable in restricted browser modes.
  }
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // Ignore storage failures.
  }
}
