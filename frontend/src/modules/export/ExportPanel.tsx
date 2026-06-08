import React, { useState } from 'react'
import { useParams } from 'react-router-dom'
import { exportApi } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Download } from 'lucide-react'

export const ExportPanel: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const [format, setFormat] = useState('txt')
  const [exporting, setExporting] = useState(false)

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
        <div className="mx-auto max-w-md space-y-6">
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
        </div>
      </div>
    </div>
  )
}
