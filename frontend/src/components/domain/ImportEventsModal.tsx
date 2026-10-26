import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import { useId, useState } from 'react'

import { normalizeApiError } from '../../api/errors'
import { importEvents } from '../../api/events'
import { formatNumber, shortId } from '../../lib/format'
import { parseEventText } from '../../lib/parseEvents'
import { Button } from '../ui/Button'
import { FormField } from '../ui/FormField'
import { Modal } from '../ui/Modal'

interface ImportEventsModalProps {
  open: boolean
  onClose: () => void
}

export function ImportEventsModal({ open, onClose }: ImportEventsModalProps) {
  const inputId = useId()
  const [text, setText] = useState('')
  const [fileName, setFileName] = useState<string | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: importEvents,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['events'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
      void queryClient.invalidateQueries({ queryKey: ['audit'] })
    },
  })

  const error = mutation.isError ? normalizeApiError(mutation.error) : null

  const handleFile = async (file: File | undefined) => {
    if (!file) return
    setFileName(file.name)
    setParseError(null)
    mutation.reset()
    try {
      setText(await file.text())
    } catch {
      setParseError('无法读取文件。')
    }
  }

  const handleSubmit = () => {
    setParseError(null)
    try {
      const events = parseEventText(text)
      mutation.mutate(events)
    } catch (cause) {
      setParseError(cause instanceof Error ? cause.message : '输入解析失败。')
    }
  }

  const handleClose = () => {
    mutation.reset()
    setParseError(null)
    onClose()
  }

  return (
    <Modal
      open={open}
      title="导入合成安全事件"
      onClose={handleClose}
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={handleClose}>
            取消
          </Button>
          <Button
            variant="primary"
            loading={mutation.isPending}
            onClick={handleSubmit}
            disabled={!text.trim()}
          >
            导入事件
          </Button>
        </>
      }
    >
      <div className="sf-stack">
        <div className="sf-alert sf-alert-info">
          支持 JSON 数组、单个 JSON 对象或 JSONL。单次 1–500 条，字段由后端再次校验。
        </div>

        <label className="sf-file-drop">
          <Upload size={18} aria-hidden="true" />
          <span>{fileName ? `已选择：${fileName}` : '选择 .json / .jsonl 文件'}</span>
          <input
            type="file"
            accept=".json,.jsonl,.txt,application/json"
            onChange={(event) => void handleFile(event.target.files?.[0])}
          />
        </label>

        <FormField
          label="事件数据"
          htmlFor={inputId}
          hint="示例：JSON 数组或每行一个事件对象。"
          error={parseError ?? undefined}
        >
          <textarea
            id={inputId}
            className="sf-textarea sf-textarea-code"
            rows={12}
            value={text}
            onChange={(event) => {
              setText(event.target.value)
              setParseError(null)
            }}
            placeholder={`[{"event_id":"...","timestamp":"2026-10-19T09:00:00Z", ...}]`}
            spellCheck={false}
          />
        </FormField>

        {error ? (
          <div className="sf-alert sf-alert-error" role="alert">
            <strong>导入失败：</strong>
            {error.message}
            {error.issues.length > 0 ? (
              <ul className="sf-issue-list">
                {error.issues.slice(0, 8).map((issue, index) => (
                  <li key={`${issue.loc.join('.')}-${index}`}>
                    {issue.loc.filter((part) => part !== 'body').join('.')}：{issue.msg}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        {mutation.isSuccess ? (
          <div className="sf-alert sf-alert-success" role="status">
            <strong>导入完成。</strong>
            <div className="sf-result-grid">
              <span>接收：{formatNumber(mutation.data.received)}</span>
              <span>导入：{formatNumber(mutation.data.imported)}</span>
              <span>跳过：{formatNumber(mutation.data.skipped)}</span>
            </div>
            {mutation.data.skipped_event_ids.length > 0 ? (
              <p className="sf-muted">
                跳过的事件 ID：{' '}
                {mutation.data.skipped_event_ids
                  .slice(0, 5)
                  .map((id) => shortId(id))
                  .join('、')}
                {mutation.data.skipped_event_ids.length > 5
                  ? ` 等 ${mutation.data.skipped_event_ids.length} 条`
                  : ''}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    </Modal>
  )
}
