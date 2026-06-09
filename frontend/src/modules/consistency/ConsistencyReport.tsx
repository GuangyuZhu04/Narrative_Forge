import React, { useEffect, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { analysisApi, getActiveLLMConfigId } from '@/services/api'
import { Button } from '@/components/ui/Button'
import { Shield, AlertTriangle, CheckCircle } from 'lucide-react'

interface ReportItem {
  id: string
  project_id: string
  chapter_id: string | null
  chapter_title: string | null
  analysis_type: string
  status: string
  issues: Record<string, unknown>[] | null
  suggestions: unknown[] | null
  score: number | null
  created_at: string
}

interface ChapterItem {
  id: string
  outline_node_id: string
  title: string
  summary: string | null
  volume_title: string | null
  sort_order: number
}

const ANALYSIS_DIMENSIONS = [
  'character_personality',
  'plot_consistency',
  'plot_continuity',
  'content_consistency',
]

const ANALYSIS_TYPE_LABELS: Record<string, string> = {
  character_personality: '人物性格',
  plot_consistency: '剧情一致性',
  plot_continuity: '剧情连贯性',
  content_consistency: '内容一致性',
}

const SEVERITY_LABELS: Record<string, string> = {
  low: '轻微',
  medium: '中等',
  high: '严重',
}

const getTextField = (
  value: Record<string, unknown>,
  key: string
): string | null => {
  const field = value[key]
  if (typeof field === 'string' && field.trim()) return field
  if (field === null || field === undefined) return null
  if (typeof field === 'number' || typeof field === 'boolean') {
    return String(field)
  }
  return null
}

const formatUnknownItem = (value: unknown): string => {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return (
      getTextField(record, 'description') ||
      getTextField(record, 'suggestion') ||
      getTextField(record, 'content') ||
      JSON.stringify(record)
    )
  }
  return ''
}

export const ConsistencyReport: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const location = useLocation()
  const [reports, setReports] = useState<ReportItem[]>([])
  const [chapters, setChapters] = useState<ChapterItem[]>([])
  const [selectedChapter, setSelectedChapter] = useState<string>('')
  const [analyzing, setAnalyzing] = useState(false)
  const isActive = projectId
    ? location.pathname === `/projects/${projectId}/consistency`
    : false

  const fetchReports = async (chapterId = selectedChapter) => {
    if (!projectId) return
    const result = (await analysisApi.getReports(
      projectId,
      chapterId || undefined
    )) as unknown as { data: ReportItem[] }
    setReports(result.data || [])
  }

  useEffect(() => {
    if (!projectId || !isActive) return
    let cancelled = false

    const loadChapters = async () => {
      const chaptersResult = (await analysisApi.getChapters(projectId)) as unknown as {
        data: ChapterItem[]
      }

      if (!cancelled) {
        const availableChapters = chaptersResult.data || []
        setChapters(availableChapters)
        setSelectedChapter((current) =>
          current && availableChapters.some((chapter) => chapter.id === current)
            ? current
            : ''
        )
      }
    }

    void loadChapters()
    return () => {
      cancelled = true
    }
  }, [projectId, isActive])

  useEffect(() => {
    if (!projectId || !isActive) return
    let cancelled = false

    const loadReports = async () => {
      const result = (await analysisApi.getReports(
        projectId,
        selectedChapter || undefined
      )) as unknown as { data: ReportItem[] }
      if (!cancelled) {
        setReports(result.data || [])
      }
    }

    void loadReports()
    return () => {
      cancelled = true
    }
  }, [projectId, selectedChapter, isActive])

  const handleAnalyze = async () => {
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId || !projectId || !selectedChapter) return
    setAnalyzing(true)
    try {
      await analysisApi.analyze(projectId, cfgId, selectedChapter, ANALYSIS_DIMENSIONS)
      await fetchReports()
    } finally {
      setAnalyzing(false)
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
      <div className="flex items-center justify-between border-b p-4">
        <h2 className="text-lg font-semibold">一致性分析</h2>
        <div className="flex items-center gap-2">
          <select
            className="rounded-md border px-3 py-1.5 text-sm"
            value={selectedChapter}
            onChange={(e) => setSelectedChapter(e.target.value)}
          >
            <option value="">全部章节</option>
            {chapters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.volume_title ? `${c.volume_title} / ${c.title}` : c.title}
              </option>
            ))}
          </select>
          <Button
            size="sm"
            onClick={handleAnalyze}
            disabled={analyzing || !selectedChapter}
          >
            <Shield className="mr-1 h-4 w-4" />
            {analyzing ? '分析中...' : '执行分析'}
          </Button>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {reports.length === 0 ? (
          <div className="text-center text-gray-500">
            暂无分析报告，请选择章节执行一致性分析
          </div>
        ) : (
          <div className="space-y-4">
            {reports.map((r) => {
              const issues = r.issues || []
              const suggestions = r.suggestions || []

              return (
                <div key={r.id} className="rounded-lg border bg-white p-4 shadow-sm">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {r.status === 'completed' ? (
                        <CheckCircle className="h-5 w-5 text-green-500" />
                      ) : (
                        <AlertTriangle className="h-5 w-5 text-yellow-500" />
                      )}
                      <span className="font-medium">
                        {ANALYSIS_TYPE_LABELS[r.analysis_type] || r.analysis_type}
                      </span>
                    </div>
                    {r.score !== null && (
                      <span className="rounded-full bg-blue-100 px-2 py-0.5 text-sm text-blue-700">
                        评分：{r.score.toFixed(1)}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 text-sm text-gray-600">
                    章节：{r.chapter_title || chapters.find((c) => c.id === r.chapter_id)?.title || '未知章节'}
                  </p>

                  {issues.length > 0 ? (
                    <div className="mt-3 space-y-2">
                      <p className="text-sm font-medium text-red-600">
                        发现 {issues.length} 个问题
                      </p>
                      {issues.map((issue, index) => {
                        const description =
                          getTextField(issue, 'description') ||
                          formatUnknownItem(issue)
                        const location = getTextField(issue, 'location')
                        const characterName = getTextField(issue, 'character_name')
                        const severity = getTextField(issue, 'severity')
                        const suggestion = getTextField(issue, 'suggestion')

                        return (
                          <div
                            key={index}
                            className="rounded-md border border-red-100 bg-red-50 p-3 text-sm"
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-red-700">
                                问题 {index + 1}
                              </span>
                              {severity && (
                                <span className="rounded-full bg-white px-2 py-0.5 text-xs text-red-600">
                                  {SEVERITY_LABELS[severity] || severity}
                                </span>
                              )}
                              {characterName && (
                                <span className="text-xs text-gray-500">
                                  人物：{characterName}
                                </span>
                              )}
                            </div>
                            {location && (
                              <p className="mt-1 text-xs text-gray-500">
                                位置：{location}
                              </p>
                            )}
                            <p className="mt-1 leading-relaxed text-gray-800">
                              {description}
                            </p>
                            {suggestion && (
                              <p className="mt-2 leading-relaxed text-gray-700">
                                <span className="font-medium">建议：</span>
                                {suggestion}
                              </p>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <p className="mt-3 rounded-md bg-green-50 px-3 py-2 text-sm text-green-700">
                      未发现明显问题
                    </p>
                  )}

                  {suggestions.length > 0 && (
                    <div className="mt-3 rounded-md bg-blue-50 p-3 text-sm">
                      <p className="font-medium text-blue-700">整体建议</p>
                      <ul className="mt-1 space-y-1 text-gray-700">
                        {suggestions.map((suggestion, index) => (
                          <li key={index}>
                            {index + 1}. {formatUnknownItem(suggestion)}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <p className="mt-2 text-xs text-gray-400">
                    {new Date(r.created_at).toLocaleString()}
                  </p>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
