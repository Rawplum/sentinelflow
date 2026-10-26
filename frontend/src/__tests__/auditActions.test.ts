import { describe, expect, it } from 'vitest'

import { AUDIT_ACTIONS, AUDIT_ACTION_LABELS } from '../lib/constants'

/**
 * The audit page can only filter and label actions it knows about. These tests
 * pin the contract with the backend's audit actions so a new action cannot be
 * silently invisible in the UI.
 */
describe('audit action catalog', () => {
  it('covers every action the backend currently emits', () => {
    const backendActions = [
      'auth.login',
      'auth.login_failed',
      'auth.login_throttled',
      'auth.logout',
      'auth.inactive_user',
      'events.import',
      'detections.run',
      'alerts.status_change',
      'reports.view',
      'reports.create',
      'reports.read',
      'reports.finalize',
      'investigations.run',
      'investigations.complete',
      'audit.view',
      'authorization.denied',
      'users.create',
    ]

    for (const action of backendActions) {
      expect(AUDIT_ACTIONS).toContain(action)
      expect(AUDIT_ACTION_LABELS[action]).toBeTruthy()
    }
  })

  it('labels every filterable action', () => {
    for (const action of AUDIT_ACTIONS) {
      expect(AUDIT_ACTION_LABELS[action], `missing label for ${action}`).toBeTruthy()
    }
  })
})
