import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { Link } from 'react-router-dom'

import { runDetection } from '../../api/detections'
import { normalizeApiError } from '../../api/errors'
import { formatNumber } from '../../lib/format'
import { Button } from '../ui/Button'

export function RunDetectionButton() {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: runDetection,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      void queryClient.invalidateQueries({ queryKey: ['audit'] })
    },
  })

  const error = mutation.isError ? normalizeApiError(mutation.error) : null

  return (
    <div className="sf-detection-control">
      <Button
        variant="primary"
        icon={<Play size={15} aria-hidden="true" />}
        loading={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? '正在检测…' : '运行检测'}
      </Button>

      {mutation.isSuccess ? (
        <div className="sf-alert sf-alert-success" role="status">
          <strong>检测完成。</strong>{' '}
          扫描 {formatNumber(mutation.data.events_scanned)} 个事件，识别{' '}
          {formatNumber(mutation.data.windows_detected)} 个窗口，创建{' '}
          {formatNumber(mutation.data.alerts_created)} 个告警，跳过{' '}
          {formatNumber(mutation.data.alerts_skipped_existing)} 个已存在告警。
          {mutation.data.created_alert_ids.length > 0 ? (
            <div className="sf-result-links">
              {mutation.data.created_alert_ids.slice(0, 3).map((alertId) => (
                <Link
                  key={alertId}
                  to={`/alerts/${alertId}/report`}
                  className="sf-inline-link"
                >
                  查看新告警报告
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? (
        <div className="sf-alert sf-alert-error" role="alert">
          {error.message}
        </div>
      ) : null}
    </div>
  )
}
