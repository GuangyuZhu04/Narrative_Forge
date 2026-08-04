import React, { useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  exportApi,
  type PlatformExportPayload,
  type PlatformExportTarget,
} from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Copy, Download, ExternalLink, Send } from 'lucide-react'

const platformOptions: {
  platform: PlatformExportTarget
  label: string
}[] = [
  { platform: 'fanqie', label: '一键导出到番茄' },
  { platform: 'qidian', label: '一键导出到起点' },
]

async function copyText(text: string) {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // Fall through to textarea copy for browsers that require a focused element.
    }
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'
  textarea.setAttribute('readonly', 'readonly')
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  const copied = document.execCommand('copy')
  document.body.removeChild(textarea)
  if (!copied) {
    throw new Error('Copy failed')
  }
}

export const ExportPanel: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [format, setFormat] = useState('txt')
  const [exporting, setExporting] = useState(false)
  const [platformExporting, setPlatformExporting] =
    useState<PlatformExportTarget | null>(null)
  const [platformNotice, setPlatformNotice] = useState<{
    type: 'success' | 'error'
    text: string
  } | null>(null)
  const [platformExportResult, setPlatformExportResult] =
    useState<PlatformExportPayload | null>(null)

  const handleExport = async () => {
    if (!projectId) return
    setExporting(true)
    try {
      const blob = await exportApi.exportProject(projectId, format) as unknown as Blob
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `novel.${format}`
      a.click()
      window.URL.revokeObjectURL(url)
    } finally {
      setExporting(false)
    }
  }

  const handlePlatformExport = async (platform: PlatformExportTarget) => {
    if (!projectId) return
    setPlatformExporting(platform)
    setPlatformNotice(null)
    setPlatformExportResult(null)
    try {
      const payload = (await exportApi.exportToPlatform(
        projectId,
        platform
      )) as unknown as PlatformExportPayload
      setPlatformExportResult(payload)

      let copied = true
      try {
        await copyText(payload.clipboard_text)
      } catch {
        copied = false
      }

      const openedWindow = window.open(
        payload.target_url,
        '_blank',
        'noopener,noreferrer'
      )

      const warningText = payload.warnings.length
        ? `，${payload.warnings.join('，')}`
        : ''
      let resultText = `已复制 ${payload.chapter_count} 章 / ${payload.total_word_count} 字，已打开${payload.platform_name}${warningText}`
      let resultType: 'success' | 'error' = 'success'
      if (copied && !openedWindow) {
        resultText = `已复制 ${payload.chapter_count} 章 / ${payload.total_word_count} 字，浏览器拦截了自动打开${warningText}`
      } else if (!copied && openedWindow) {
        resultText = `已打开${payload.platform_name}，自动复制失败${warningText}`
        resultType = 'error'
      } else if (!copied && !openedWindow) {
        resultText = `自动复制和打开均失败${warningText}`
        resultType = 'error'
      }
      setPlatformNotice({ type: resultType, text: resultText })
    } catch {
      setPlatformNotice({ type: 'error', text: '平台导出失败，请稍后重试' })
    } finally {
      setPlatformExporting(null)
    }
  }

  const handleManualCopy = async () => {
    if (!platformExportResult) return
    try {
      await copyText(platformExportResult.clipboard_text)
      const warningText = platformExportResult.warnings.length
        ? `，${platformExportResult.warnings.join('，')}`
        : ''
      setPlatformNotice({
        type: 'success',
        text: `已复制 ${platformExportResult.chapter_count} 章 / ${platformExportResult.total_word_count} 字${warningText}`,
      })
    } catch {
      setPlatformNotice({
        type: 'error',
        text: '复制失败，可选中下方文本后手动复制',
      })
    }
  }

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center text-gray-500">
        请先选择项目
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-4">
        <h2 className="text-lg font-semibold">导出</h2>
      </div>
      <div className="flex-1 p-4">
        <div className="mx-auto max-w-2xl space-y-6">
          <div>
            <label className="mb-2 block text-sm font-medium text-gray-700">
              导出格式
            </label>
            <div className="flex gap-4">
              {['txt', 'markdown', 'docx'].map((f) => (
                <label key={f} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="format"
                    value={f}
                    checked={format === f}
                    onChange={() => setFormat(f)}
                  />
                  <span className="text-sm">
                    {f === 'txt'
                      ? '纯文本 (TXT)'
                      : f === 'markdown'
                        ? 'Markdown'
                        : 'Word (DOCX)'}
                  </span>
                </label>
              ))}
            </div>
          </div>
          <Button
            className="w-full"
            onClick={handleExport}
            disabled={exporting}
          >
            <Download className="mr-2 h-4 w-4" />
            {exporting ? '导出中...' : '导出项目'}
          </Button>
          <div className="space-y-3 border-t pt-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-medium text-gray-700">平台导出</h3>
              {platformExporting && (
                <span className="text-xs text-gray-500">处理中...</span>
              )}
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {platformOptions.map((item) => (
                <Button
                  key={item.platform}
                  variant="outline"
                  onClick={() => handlePlatformExport(item.platform)}
                  disabled={Boolean(platformExporting)}
                >
                  <Send className="mr-2 h-4 w-4" />
                  {platformExporting === item.platform
                    ? '导出中...'
                    : item.label}
                  <ExternalLink className="ml-2 h-4 w-4" />
                </Button>
              ))}
            </div>
            {platformNotice && (
              <div
                className={`rounded-md border px-3 py-2 text-sm ${
                  platformNotice.type === 'success'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'border-red-200 bg-red-50 text-red-700'
                }`}
              >
                {platformNotice.text}
              </div>
            )}
            {platformExportResult && platformNotice?.type === 'error' && (
              <div className="space-y-3 rounded-md border border-gray-200 bg-gray-50 p-3">
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" onClick={handleManualCopy}>
                    <Copy className="mr-2 h-4 w-4" />
                    复制投稿文本
                  </Button>
                  <a
                    className="inline-flex items-center justify-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    href={platformExportResult.target_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    打开{platformExportResult.platform_name}
                    <ExternalLink className="ml-2 h-4 w-4" />
                  </a>
                </div>
                <textarea
                  className="h-40 w-full resize-y rounded-md border border-gray-300 bg-white p-3 text-sm leading-6 text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  readOnly
                  value={platformExportResult.clipboard_text}
                  onFocus={(event) => event.currentTarget.select()}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
