export type UserRole = 'admin' | 'analyst';

export type EventOutcome = 'success' | 'failure' | 'unknown';

export type AlertSeverity = 'info' | 'low' | 'medium' | 'high' | 'critical';

export type AlertStatus =
  | 'open'
  | 'acknowledged'
  | 'investigating'
  | 'closed';

export type RiskLevel = 'low' | 'medium' | 'high' | 'critical';

export type AuditOutcome = 'success' | 'failure' | 'denied';

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  username: string;
  role: UserRole;
}

export interface CurrentUser {
  id: string;
  username: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface SecurityEvent {
  event_id: string;
  timestamp: string;
  event_type: string;
  username: string | null;
  source_ip: string | null;
  asset_id: string | null;
  action: string;
  outcome: EventOutcome;
  // Null when the request opted out of raw payloads.
  raw_message: string | null;
  source: string;
  created_at: string;
}

export interface SecurityEventCreate {
  event_id: string;
  timestamp: string;
  event_type: string;
  username?: string | null;
  source_ip?: string | null;
  asset_id?: string | null;
  action: string;
  outcome: EventOutcome;
  raw_message: string;
  source: string;
}

export interface EventImportRequest {
  events: SecurityEventCreate[];
}

export interface EventImportResponse {
  received: number;
  imported: number;
  skipped: number;
  skipped_event_ids: string[];
}

export interface DetectionRunResponse {
  rule_id: string;
  rule_version: string;
  events_scanned: number;
  windows_detected: number;
  alerts_created: number;
  alerts_skipped_existing: number;
  created_alert_ids: string[];
}

export interface Alert {
  id: string;
  rule_id: string;
  rule_version: string;
  title: string;
  description: string;
  severity: string;
  status: string;
  first_seen_at: string;
  last_seen_at: string;
  event_count: number;
  created_at: string;
  evidence_count: number;
}

export interface ReportEvidence {
  event_id: string;
  timestamp: string;
  event_type: string;
  username: string | null;
  source_ip: string | null;
  asset_id: string | null;
  action: string;
  outcome: string;
  source: string;
  raw_message: string | null;
}

export interface ReportTimelineItem {
  timestamp: string;
  event_id: string;
  description: string;
}

export interface InvestigationReport {
  alert_id: string;
  summary: string;
  risk_level: RiskLevel;
  evidence: ReportEvidence[];
  timeline: ReportTimelineItem[];
  reasoning: string;
  recommended_actions: string[];
  limitations: string[];
  evidence_total: number;
  evidence_truncated: boolean;
}

export interface AlertStatusHistoryEntry {
  from_status: AlertStatus | null;
  to_status: AlertStatus;
  changed_by_username: string | null;
  reason: string | null;
  created_at: string;
}

export interface AlertDetail extends Alert {
  status_history: AlertStatusHistoryEntry[];
}

export type ReportStatus = 'draft' | 'finalized' | 'superseded';

export interface InvestigationReportVersion {
  id: string;
  alert_id: string;
  version: number;
  status: ReportStatus;
  generator: 'deterministic' | 'agent';
  generator_version: string;
  evidence_count: number;
  evidence_truncated: boolean;
  created_by_username: string | null;
  created_at: string;
  finalized_at: string | null;
  finalized_by_username: string | null;
  content: InvestigationReport;
}

export interface InvestigationReportList {
  items: InvestigationReportVersion[];
  total: number;
}

export interface AuditLog {
  id: string;
  actor_user_id: string | null;
  actor_username: string | null;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  outcome: AuditOutcome;
  source_ip: string | null;
  request_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface HealthResponse {
  status: 'ok';
  service: string;
  version: string;
  environment: string;
}

export type InvestigationStatus =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'limit_reached';

export type InvestigationRoundOutcome =
  | 'tool_calls'
  | 'findings'
  | 'error'
  | 'budget_exhausted';

export type InvestigationToolStatus =
  | 'ok'
  | 'error'
  | 'timeout'
  | 'denied'
  | 'invalid';

export interface InvestigationRound {
  round_index: number;
  attempt_index: number;
  latency_ms: number;
  outcome: InvestigationRoundOutcome;
  tool_call_count: number;
  error: string | null;
  created_at: string;
}

export interface InvestigationToolCall {
  sequence: number;
  attempt_index: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  status: InvestigationToolStatus;
  result_summary: Record<string, unknown> | null;
  error: string | null;
  duration_ms: number;
  created_at: string;
}

export interface Investigation {
  id: string;
  alert_id: string;
  status: InvestigationStatus;
  model_provider: string | null;
  model_name: string | null;
  prompt_version: string;
  rounds_used: number;
  tool_calls_used: number;
  error: string | null;
  error_code: string | null;
  attempt_count: number;
  max_attempts: number;
  request_id: string | null;
  duration_ms: number | null;
  report_id: string | null;
  created_by_username: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  rounds: InvestigationRound[];
  tool_calls: InvestigationToolCall[];
}
