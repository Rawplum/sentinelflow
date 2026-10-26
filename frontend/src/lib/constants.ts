export const APP_NAME = 'SentinelFlow'

export const PAGE_SIZES: number[] = [20, 50, 100]
export const DEFAULT_PAGE_SIZE = 50

export const AUDIT_ACTIONS = [
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

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  'auth.login': '登录成功',
  'auth.login_failed': '登录失败',
  'auth.login_throttled': '登录被限流',
  'auth.logout': '登出并撤销令牌',
  'auth.inactive_user': '禁用账户访问',
  'events.import': '导入事件',
  'detections.run': '运行检测',
  'alerts.status_change': '变更告警状态',
  'reports.view': '查看报告',
  'reports.create': '创建报告版本',
  'reports.read': '读取报告版本',
  'reports.finalize': '定稿报告',
  'investigations.run': '发起 AI 调查',
  'investigations.complete': 'AI 调查结束',
  'audit.view': '查看审计',
  'authorization.denied': '权限拒绝',
  'users.create': '创建用户',
}

export const SEVERITY_LABELS: Record<string, string> = {
  critical: '严重',
  high: '高',
  medium: '中',
  low: '低',
  info: '信息',
}

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

export const STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  acknowledged: '已确认',
  investigating: '调查中',
  closed: '已关闭',
}

export const OUTCOME_LABELS: Record<string, string> = {
  success: '成功',
  failure: '失败',
  unknown: '未知',
  denied: '拒绝',
}

export const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  analyst: '分析员',
}

export const RULE_ID = 'AUTH-001'
export const RULE_VERSION = '1.0.0'

export const LOCAL_ONLY_NOTICE =
  '仅限本地开发环境。认证与 RBAC 已启用，但仍缺少 TLS、登录限流、MFA、令牌撤销和审计保留策略。'

/**
 * Investigation statuses the backend can return.
 * Must stay in sync with `InvestigationStatus` in src/api/types.ts and with
 * `InvestigationStatus` in src/sentinelflow/schemas/investigations.py.
 */
export const INVESTIGATION_STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  running: '进行中',
  succeeded: '已完成',
  failed: '失败',
  limit_reached: '已达执行上限',
}

export const ROUND_OUTCOME_LABELS: Record<string, string> = {
  tool_calls: '调用工具',
  findings: '给出结论',
  error: '模型/校验错误',
  budget_exhausted: '预算耗尽',
}

export const TOOL_CALL_STATUS_LABELS: Record<string, string> = {
  ok: '成功',
  error: '执行失败',
  timeout: '超时',
  denied: '已拦截',
  invalid: '参数非法',
}
