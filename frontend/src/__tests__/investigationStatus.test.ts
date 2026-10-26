import { describe, expect, it } from 'vitest'

import {
  INVESTIGATION_STATUS_LABELS,
  ROUND_OUTCOME_LABELS,
  TOOL_CALL_STATUS_LABELS,
} from '../lib/constants'

/**
 * The panel can only label states it knows about. These tests pin the contract
 * with the backend so a new status cannot silently render as a raw enum value.
 *
 * Source of truth:
 *   src/sentinelflow/schemas/investigations.py  (InvestigationStatus, RoundOutcome, ToolCallStatus)
 *   src/sentinelflow/models/investigation.py    (CHECK constraints)
 */
describe('investigation status contract', () => {
  it('labels every status the backend can persist', () => {
    // pending -> running -> succeeded | failed | limit_reached
    const backendStatuses = [
      'pending',
      'running',
      'succeeded',
      'failed',
      'limit_reached',
    ]

    expect(Object.keys(INVESTIGATION_STATUS_LABELS).sort()).toEqual(
      [...backendStatuses].sort(),
    )
    for (const status of backendStatuses) {
      expect(
        INVESTIGATION_STATUS_LABELS[status],
        `missing label for ${status}`,
      ).toBeTruthy()
    }
  })

  it('labels every round outcome the backend can record', () => {
    const backendOutcomes = [
      'tool_calls',
      'findings',
      'error',
      'budget_exhausted',
    ]

    expect(Object.keys(ROUND_OUTCOME_LABELS).sort()).toEqual(
      [...backendOutcomes].sort(),
    )
  })

  it('labels every tool-call status the backend can record', () => {
    const backendToolStatuses = ['ok', 'error', 'timeout', 'denied', 'invalid']

    expect(Object.keys(TOOL_CALL_STATUS_LABELS).sort()).toEqual(
      [...backendToolStatuses].sort(),
    )
  })

  it('treats only terminal statuses as finished', () => {
    // Mirrors TERMINAL in InvestigationPanel: polling must continue otherwise.
    const terminal = ['succeeded', 'failed', 'limit_reached']
    const nonTerminal = ['pending', 'running']

    for (const status of [...terminal, ...nonTerminal]) {
      expect(INVESTIGATION_STATUS_LABELS[status]).toBeTruthy()
    }
    expect(terminal).not.toContain('pending')
    expect(terminal).not.toContain('running')
  })
})
