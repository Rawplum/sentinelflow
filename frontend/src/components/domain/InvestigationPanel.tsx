import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, CircleAlert, RefreshCw, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { getReportVersion } from '../../api/alerts'
import { getInvestigation, startInvestigation } from '../../api/investigations'
import { normalizeApiError } from '../../api/errors'
import type { Investigation, InvestigationStatus } from '../../api/types'
import { useAuth } from '../../auth/useAuth'
import {
  INVESTIGATION_STATUS_LABELS,
  ROUND_OUTCOME_LABELS,
  TOOL_CALL_STATUS_LABELS,
} from '../../lib/constants'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Spinner } from '../ui/Spinner'
import { formatDateTime, shortId } from '../../lib/format'

const TERMINAL: InvestigationStatus[] = ['succeeded', 'failed', 'limit_reached']

function isTerminal(status: InvestigationStatus): boolean {
  return TERMINAL.includes(status)
}

function StatusPill({ status }: { status: InvestigationStatus }) {
  return (
    <span className={`sf-badge sf-investigation-${status}`}>
      {INVESTIGATION_STATUS_LABELS[status] ?? status}
    </span>
  )
}

/**
 * Admin-only panel that starts an investigation and follows it to completion.
 *
 * The investigation id lives in the URL (?investigation=...) so a page refresh
 * resumes polling instead of losing the run. All authorization is enforced by
 * the backend; hiding the button is only a convenience.
 */
export function InvestigationPanel({ alertId }: { alertId: string }) {
  const { isAdmin } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [startError, setStartError] = useState<string | null>(null)

  const investigationId = searchParams.get('investigation')

  const investigationQuery = useQuery({
    queryKey: ['investigation', investigationId],
    queryFn: () => getInvestigation(investigationId as string),
    enabled: Boolean(investigationId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && isTerminal(status) ? false : 1500
    },
    // A 404 is definitive: retrying only delays the error state.
    retry: (failureCount, error) => {
      if (normalizeApiError(error).status === 404) return false
      return failureCount < 1
    },
  })

  const startMutation = useMutation({
    mutationFn: () => startInvestigation(alertId),
    onMutate: () => setStartError(null),
    onSuccess: (investigation) => {
      setSearchParams({ investigation: investigation.id }, { replace: true })
      void queryClient.invalidateQueries({
        queryKey: ['investigation', investigation.id],
      })
    },
    onError: (error) => setStartError(normalizeApiError(error).message),
  })

  const investigation: Investigation | undefined = investigationQuery.data
  const reportQuery = useQuery({
    queryKey: ['report-version', investigation?.report_id],
    queryFn: () => getReportVersion(investigation?.report_id as string),
    enabled: Boolean(investigation?.report_id),
  })

  const startDisabled =
    startMutation.isPending ||
    investigation?.status === 'running' ||
    investigation?.status === 'pending'

  return (
    <Card
      title="AI 调查"
      subtitle="Agent investigation"
      actions={<Bot size={16} aria-hidden="true" />}
    >
      {!isAdmin ? (
        <p className="sf-muted">
          仅管理员可以发起 AI 调查。分析员可以查看已有调查结果。
        </p>
      ) : (
        <div className="sf-investigation-toolbar">
          <Button
            variant="primary"
            icon={<Bot size={15} aria-hidden="true" />}
            loading={startDisabled}
            onClick={() => startMutation.mutate()}
          >
            {startMutation.isPending
              ? '正在创建…'
              : investigation?.status === 'pending'
                ? '已排队，等待执行…'
                : investigation?.status === 'running'
                  ? '调查进行中…'
                  : investigation
                    ? '重新调查'
                    : '启动 AI 调查'}
          </Button>
          <span className="sf-muted">
            只读工具、最多 5 轮 / 8 次工具调用；结论需人工审核后才可定稿。
          </span>
        </div>
      )}

      {startError ? (
        <div className="sf-alert sf-alert-error" role="alert">
          无法启动调查：{startError}
        </div>
      ) : null}

      {investigationId && investigationQuery.isError ? (
        <div className="sf-alert sf-alert-error" role="alert">
          无法读取调查 {shortId(investigationId)}：
          {normalizeApiError(investigationQuery.error).message}
          <button
            type="button"
            className="sf-link-button"
            onClick={() => void investigationQuery.refetch()}
          >
            <RefreshCw size={14} aria-hidden="true" />
            重试
          </button>
        </div>
      ) : null}

      {investigationQuery.isLoading ? <Spinner label="正在加载调查…" /> : null}

      {investigation ? (
        <div className="sf-investigation">
          <dl className="sf-investigation-meta">
            <div>
              <dt>状态</dt>
              <dd>
                <StatusPill status={investigation.status} />
              </dd>
            </div>
            <div>
              <dt>任务 ID</dt>
              <dd className="sf-mono" title={investigation.id}>
                {shortId(investigation.id, 12)}
              </dd>
            </div>
            <div>
              <dt>模型</dt>
              <dd className="sf-mono">
                {investigation.model_provider ?? '—'} /{' '}
                {investigation.model_name ?? '—'}
              </dd>
            </div>
            <div>
              <dt>耗时</dt>
              <dd>
                {investigation.duration_ms === null
                  ? '—'
                  : `${investigation.duration_ms} ms`}
              </dd>
            </div>
            <div>
              <dt>预算</dt>
              <dd>
                {investigation.rounds_used} 轮 / {investigation.tool_calls_used}{' '}
                次调用
              </dd>
            </div>
            <div>
              <dt>创建</dt>
              <dd>
                {formatDateTime(investigation.created_at)}
                {investigation.created_by_username
                  ? ` · ${investigation.created_by_username}`
                  : ''}
              </dd>
            </div>
          </dl>

          {investigation.status === 'pending' ? (
            <p className="sf-muted">
              任务已持久化入队，等待工作进程领取。刷新或关闭页面不会丢失。
            </p>
          ) : null}

          {investigation.status === 'running' ? (
            <p className="sf-muted">
              调查正在后台执行，页面会自动刷新状态。刷新页面不会中断调查。
            </p>
          ) : null}

          {investigation.attempt_count > 1 ? (
            <p className="sf-muted">
              已尝试 {investigation.attempt_count} / {investigation.max_attempts} 次
              （仅对可恢复的临时错误重试）。
            </p>
          ) : null}

          {investigation.error ? (
            <div className="sf-alert sf-alert-error" role="alert">
              <CircleAlert size={15} aria-hidden="true" />
              <span>{investigation.error}</span>
            </div>
          ) : null}

          {investigation.rounds.length > 0 ? (
            <section className="sf-investigation-section">
              <h3>执行步骤</h3>
              <div className="sf-table-wrap">
                <table className="sf-table">
                  <thead>
                    <tr>
                      <th>轮次</th>
                      <th>结果</th>
                      <th>耗时</th>
                      <th>工具数</th>
                      <th>错误</th>
                    </tr>
                  </thead>
                  <tbody>
                    {investigation.rounds.map((round) => (
                      <tr key={round.round_index}>
                        <td>{round.round_index}</td>
                        <td>{ROUND_OUTCOME_LABELS[round.outcome] ?? round.outcome}</td>
                        <td>{round.latency_ms} ms</td>
                        <td>{round.tool_call_count}</td>
                        <td className="sf-muted">{round.error ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {investigation.tool_calls.length > 0 ? (
            <section className="sf-investigation-section">
              <h3>工具调用</h3>
              <div className="sf-table-wrap">
                <table className="sf-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>工具</th>
                      <th>状态</th>
                      <th>耗时</th>
                      <th>结果摘要</th>
                    </tr>
                  </thead>
                  <tbody>
                    {investigation.tool_calls.map((call) => (
                      <tr key={call.sequence}>
                        <td>{call.sequence}</td>
                        <td className="sf-mono">{call.tool_name}</td>
                        <td>{TOOL_CALL_STATUS_LABELS[call.status] ?? call.status}</td>
                        <td>{call.duration_ms} ms</td>
                        <td className="sf-muted sf-mono">
                          {call.result_summary
                            ? JSON.stringify(call.result_summary)
                            : (call.error ?? '—')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {investigation.report_id ? (
            <section className="sf-investigation-section">
              <h3>
                <ShieldCheck size={15} aria-hidden="true" /> 调查产出的草稿报告
              </h3>
              {reportQuery.isLoading ? <Spinner label="加载报告…" /> : null}
              {reportQuery.data ? (
                <div className="sf-investigation-report">
                  <p>{reportQuery.data.content.summary}</p>
                  <p className="sf-muted">
                    风险等级 {reportQuery.data.content.risk_level} · 版本 v
                    {reportQuery.data.version} · {reportQuery.data.status} ·
                    引用证据 {reportQuery.data.content.evidence.length} 条
                  </p>
                  <ul className="sf-mono sf-evidence-id-list">
                    {reportQuery.data.content.evidence.map((item) => (
                      <li key={item.event_id}>{item.event_id}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </section>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
