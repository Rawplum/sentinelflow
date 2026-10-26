import { http, HttpResponse } from 'msw'

import type {
  Alert,
  AuditLog,
  CurrentUser,
  Investigation,
  InvestigationReport,
  InvestigationReportVersion,
  SecurityEvent,
} from '../../api/types'

export const adminUser: CurrentUser = {
  id: '11111111-1111-4111-8111-111111111111',
  username: 'admin.test',
  role: 'admin',
  is_active: true,
  created_at: '2026-10-19T08:00:00Z',
  last_login_at: '2026-10-19T09:00:00Z',
}

export const analystUser: CurrentUser = {
  ...adminUser,
  id: '22222222-2222-4222-8222-222222222222',
  username: 'analyst.test',
  role: 'analyst',
}

export const events: SecurityEvent[] = [
  {
    event_id: '33333333-3333-4333-8333-333333333333',
    timestamp: '2026-10-19T09:00:00Z',
    event_type: 'authentication',
    username: 'alice.demo',
    source_ip: '198.51.100.10',
    asset_id: 'workstation-01',
    action: 'login',
    outcome: 'failure',
    raw_message: 'synthetic event: failed password for alice.demo',
    source: 'synthetic-auth',
    created_at: '2026-10-19T09:00:05Z',
  },
  {
    event_id: '44444444-4444-4444-8444-444444444444',
    timestamp: '2026-10-19T09:01:00Z',
    event_type: 'authentication',
    username: 'bob.demo',
    source_ip: '203.0.113.20',
    asset_id: 'workstation-02',
    action: 'login',
    outcome: 'success',
    raw_message: 'synthetic event: accepted password for bob.demo',
    source: 'synthetic-auth',
    created_at: '2026-10-19T09:01:05Z',
  },
]

export const alerts: Alert[] = [
  {
    id: '55555555-5555-4555-8555-555555555555',
    rule_id: 'AUTH-001',
    rule_version: '1.0.0',
    title: 'Suspicious login activity',
    description:
      "5 failed authentication attempts for user 'alice.demo' from 198.51.100.10 matched rule AUTH-001.",
    severity: 'high',
    status: 'open',
    first_seen_at: '2026-10-19T09:00:00Z',
    last_seen_at: '2026-10-19T09:04:00Z',
    event_count: 5,
    created_at: '2026-10-19T09:05:00Z',
    evidence_count: 5,
  },
  {
    id: '66666666-6666-4666-8666-666666666666',
    rule_id: 'AUTH-001',
    rule_version: '1.0.0',
    title: 'Synthetic medium alert',
    description: 'Synthetic alert for UI testing.',
    severity: 'medium',
    status: 'closed',
    first_seen_at: '2026-10-18T09:00:00Z',
    last_seen_at: '2026-10-18T09:04:00Z',
    event_count: 5,
    created_at: '2026-10-18T09:05:00Z',
    evidence_count: 5,
  },
]

export const report: InvestigationReport = {
  alert_id: alerts[0].id,
  summary:
    "Rule AUTH-001 identified 5 failed authentication attempts for user 'alice.demo' from 198.51.100.10.",
  risk_level: 'high',
  evidence: [
    {
      event_id: events[0].event_id,
      timestamp: events[0].timestamp,
      event_type: events[0].event_type,
      username: events[0].username,
      source_ip: events[0].source_ip,
      asset_id: events[0].asset_id,
      action: events[0].action,
      outcome: events[0].outcome,
      source: events[0].source,
      raw_message: events[0].raw_message,
    },
  ],
  timeline: [
    {
      timestamp: events[0].timestamp,
      event_id: events[0].event_id,
      description:
        "login failure for user 'alice.demo' from 198.51.100.10 on asset 'workstation-01'",
    },
  ],
  reasoning:
    'Rule AUTH-001 fires when the same username and source IP produce at least 5 failures within a 5-minute window.',
  recommended_actions: [
    'Verify whether the source IP is expected for this user.',
    'Review authentication logs around the alert window.',
  ],
  limitations: [
    'This rule detects a pattern; it does not prove that a system was compromised.',
  ],
  evidence_total: 5,
  evidence_truncated: false,
}


export const investigationPending: Investigation = {
  id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
  alert_id: alerts[0].id,
  status: 'pending',
  model_provider: 'mock',
  model_name: 'mock-investigator',
  prompt_version: '1.0.0',
  rounds_used: 0,
  tool_calls_used: 0,
  error: null,
  error_code: null,
  attempt_count: 0,
  max_attempts: 2,
  request_id: 'request-eval-1',
  duration_ms: null,
  report_id: null,
  created_by_username: adminUser.username,
  created_at: '2026-10-19T09:10:00Z',
  started_at: null,
  completed_at: null,
  rounds: [],
  tool_calls: [],
}

export const investigationRunning: Investigation = {
  id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  alert_id: alerts[0].id,
  status: 'running',
  model_provider: 'mock',
  model_name: 'mock-investigator',
  prompt_version: '1.0.0',
  rounds_used: 0,
  tool_calls_used: 0,
  error: null,
  error_code: null,
  attempt_count: 1,
  max_attempts: 2,
  request_id: 'request-eval-1',
  duration_ms: null,
  report_id: null,
  created_by_username: adminUser.username,
  created_at: '2026-10-19T09:10:00Z',
  started_at: '2026-10-19T09:10:00Z',
  completed_at: null,
  rounds: [],
  tool_calls: [],
}

export const investigationSucceeded: Investigation = {
  ...investigationRunning,
  id: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc',
  status: 'succeeded',
  rounds_used: 2,
  tool_calls_used: 1,
  duration_ms: 145,
  report_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  completed_at: '2026-10-19T09:10:01Z',
  rounds: [
    {
      round_index: 1,
      attempt_index: 1,
      latency_ms: 60,
      outcome: 'tool_calls',
      tool_call_count: 1,
      error: null,
      created_at: '2026-10-19T09:10:00Z',
    },
    {
      round_index: 2,
      attempt_index: 1,
      latency_ms: 85,
      outcome: 'findings',
      tool_call_count: 0,
      error: null,
      created_at: '2026-10-19T09:10:01Z',
    },
  ],
  tool_calls: [
    {
      sequence: 1,
      attempt_index: 1,
      tool_name: 'get_related_events',
      arguments: { limit: 5 },
      status: 'ok',
      result_summary: { returned: 1, total: 5, offset: 0 },
      error: null,
      duration_ms: 4,
      created_at: '2026-10-19T09:10:00Z',
    },
  ],
}

export const reportVersion: InvestigationReportVersion = {
  id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
  alert_id: alerts[0].id,
  version: 1,
  status: 'draft',
  generator: 'agent',
  generator_version: '1.0.0',
  evidence_count: 1,
  evidence_truncated: true,
  created_by_username: adminUser.username,
  created_at: '2026-10-19T09:10:01Z',
  finalized_at: null,
  finalized_by_username: null,
  content: report,
}

export const auditLogs: AuditLog[] = [
  {
    id: '77777777-7777-4777-8777-777777777777',
    actor_user_id: adminUser.id,
    actor_username: adminUser.username,
    action: 'events.import',
    resource_type: null,
    resource_id: null,
    outcome: 'success',
    source_ip: '127.0.0.1',
    request_id: 'request-1',
    details: { received: 5, imported: 5, skipped: 0 },
    created_at: '2026-10-19T09:05:00Z',
  },
  {
    id: '88888888-8888-4888-8888-888888888888',
    actor_user_id: adminUser.id,
    actor_username: adminUser.username,
    action: 'auth.login',
    resource_type: null,
    resource_id: null,
    outcome: 'success',
    source_ip: '127.0.0.1',
    request_id: 'request-2',
    details: { role: 'admin' },
    created_at: '2026-10-19T09:00:00Z',
  },
  {
    id: '99999999-9999-4999-8999-999999999999',
    actor_user_id: adminUser.id,
    actor_username: adminUser.username,
    action: 'detections.run',
    resource_type: null,
    resource_id: null,
    outcome: 'success',
    source_ip: '127.0.0.1',
    request_id: 'request-3',
    details: { alerts_created: 1, events_scanned: 5 },
    created_at: '2026-10-19T09:06:00Z',
  },
]

export const handlers = [
  http.post('*/api/v1/auth/login', async ({ request }) => {
    const body = (await request.json()) as {
      username?: string
      password?: string
    }
    if (body.password === 'wrong-password') {
      return HttpResponse.json(
        { detail: 'Invalid username or password' },
        { status: 401 },
      )
    }
    return HttpResponse.json({
      access_token: 'test-access-token',
      token_type: 'bearer',
      expires_in: 1800,
      username: body.username ?? 'admin.test',
      role: 'admin',
    })
  }),

  http.get('*/api/v1/auth/me', () => HttpResponse.json(adminUser)),

  http.get('*/api/v1/events', ({ request }) => {
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? '50')
    const offset = Number(url.searchParams.get('offset') ?? '0')
    return HttpResponse.json({
      items: events.slice(offset, offset + limit),
      total: events.length,
      limit,
      offset,
    })
  }),

  http.post('*/api/v1/events/import', async ({ request }) => {
    const body = (await request.json()) as { events?: unknown[] }
    const count = body.events?.length ?? 0
    return HttpResponse.json(
      {
        received: count,
        imported: count,
        skipped: 0,
        skipped_event_ids: [],
      },
      { status: 201 },
    )
  }),

  http.post('*/api/v1/detections/run', () =>
    HttpResponse.json({
      rule_id: 'AUTH-001',
      rule_version: '1.0.0',
      events_scanned: 5,
      windows_detected: 1,
      alerts_created: 1,
      alerts_skipped_existing: 0,
      created_alert_ids: [alerts[0].id],
    }),
  ),

  http.get('*/api/v1/alerts', ({ request }) => {
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? '50')
    const offset = Number(url.searchParams.get('offset') ?? '0')
    return HttpResponse.json({
      items: alerts.slice(offset, offset + limit),
      total: alerts.length,
      limit,
      offset,
    })
  }),

  http.get('*/api/v1/alerts/:alertId', ({ params }) => {
    const alert = alerts.find((item) => item.id === params.alertId)
    if (!alert) {
      return HttpResponse.json({ detail: 'Alert not found' }, { status: 404 })
    }
    return HttpResponse.json({ ...alert, status_history: [] })
  }),

  http.get('*/api/v1/alerts/:alertId/reports', ({ params }) => {
    if (params.alertId !== report.alert_id) {
      return HttpResponse.json({ detail: 'Alert not found' }, { status: 404 })
    }
    return HttpResponse.json({ items: [], total: 0 })
  }),

  http.get('*/api/v1/alerts/:alertId/report', ({ params }) => {
    if (params.alertId !== report.alert_id) {
      return HttpResponse.json({ detail: 'Alert not found' }, { status: 404 })
    }
    return HttpResponse.json(report)
  }),


  http.post('*/api/v1/alerts/:alertId/investigations', () =>
    HttpResponse.json(investigationPending, { status: 202 }),
  ),

  http.get('*/api/v1/investigations/:investigationId', ({ params }) => {
    if (params.investigationId === investigationPending.id) {
      return HttpResponse.json(investigationPending)
    }
    if (params.investigationId === investigationRunning.id) {
      return HttpResponse.json(investigationRunning)
    }
    if (params.investigationId === investigationSucceeded.id) {
      return HttpResponse.json(investigationSucceeded)
    }
    return HttpResponse.json(
      { detail: 'Investigation not found' },
      { status: 404 },
    )
  }),

  http.get('*/api/v1/reports/:reportId', ({ params }) => {
    if (params.reportId === reportVersion.id) {
      return HttpResponse.json(reportVersion)
    }
    return HttpResponse.json({ detail: 'Report not found' }, { status: 404 })
  }),

  http.get('*/api/v1/audit-logs', ({ request }) => {
    const url = new URL(request.url)
    const limit = Number(url.searchParams.get('limit') ?? '50')
    const offset = Number(url.searchParams.get('offset') ?? '0')
    const action = url.searchParams.get('action')
    const filtered = action
      ? auditLogs.filter((entry) => entry.action === action)
      : auditLogs
    return HttpResponse.json({
      items: filtered.slice(offset, offset + limit),
      total: filtered.length,
      limit,
      offset,
    })
  }),
]
