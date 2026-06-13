import React, { useEffect, useState, useCallback, useRef } from 'react'
import { useParams } from 'react-router-dom'
import {
  analysisApi,
  chapterApi,
  getActiveLLMConfigId,
} from '@/services/api'
import { useOutlineStore } from '@/stores/outlineStore'
import { Button } from '@/components/ui/Button'
import { Modal } from '@/components/ui/Modal'
import {
  Sparkles,
  ChevronRight,
  ChevronDown,
  Loader2,
  Save,
  RefreshCw,
  BookOpen,
  FileText,
} from 'lucide-react'
import type { OutlineNode } from '@/types'

interface ChapterItem {
  id: string
  title: string
  content: string | null
  summary: string | null
  outline_node_id: string | null
  sort_order: number
  status: string
  word_count: number
}

type ToastType = 'success' | 'error'

interface Toast {
  id: number
  type: ToastType
  message: string
}

interface NovelWriteContext {
  chapter_id: string
  outline_id: string | null
  outline_title: string | null
  outline_context: string
  volume_node_id: string | null
  volume_title: string | null
  volume_context: string
  chapter_title: string
  outline_node_id: string | null
  outline_node_title: string | null
  chapter_summary: string
  character_definitions: string
  characters?: NovelWriteCharacter[]
  character_count: number
  scene_context: string
  scenes?: NovelWriteScene[]
  scene_count: number
  previous_chapter_title: string | null
  previous_context: string
  previous_chapter_content: string
  style_requirements: string
}

interface NovelWriteCharacter {
  id: string
  name: string
  aliases: string[]
  definition: string
  selected: boolean
}

interface NovelWriteScene {
  id: string
  name: string
  definition: string
  selected: boolean
}

interface SceneOrderUpdatedDetail {
  projectId: string
  scenes: Array<{ id: string; sort_order: number }>
}

interface AnalysisReportItem {
  analysis_type: string
  issues: unknown[] | null
  suggestions: unknown[] | null
  score: number | null
}

type EditableNovelWriteContextKey =
  | 'outline_context'
  | 'volume_context'
  | 'chapter_title'
  | 'chapter_summary'
  | 'character_definitions'
  | 'scene_context'
  | 'previous_context'
  | 'previous_chapter_content'
  | 'style_requirements'

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

const formatAnalysisReportsForPolish = (
  reports: AnalysisReportItem[]
): string => {
  return reports
    .map((report) => {
      const label =
        ANALYSIS_TYPE_LABELS[report.analysis_type] || report.analysis_type
      const lines = [`【${label}】`]
      if (typeof report.score === 'number') {
        lines.push(`评分：${report.score.toFixed(1)}`)
      }

      const issues = report.issues || []
      if (issues.length > 0) {
        lines.push('问题：')
        issues.forEach((issue, index) => {
          if (issue && typeof issue === 'object') {
            const record = issue as Record<string, unknown>
            const severity = getTextField(record, 'severity')
            const location = getTextField(record, 'location')
            const characterName = getTextField(record, 'character_name')
            const description =
              getTextField(record, 'description') || formatUnknownItem(issue)
            const suggestion = getTextField(record, 'suggestion')
            const parts = [`${index + 1}. ${description}`]
            if (severity) {
              parts.push(`严重程度：${SEVERITY_LABELS[severity] || severity}`)
            }
            if (location) parts.push(`位置：${location}`)
            if (characterName) parts.push(`人物：${characterName}`)
            if (suggestion) parts.push(`建议：${suggestion}`)
            lines.push(parts.join('；'))
          } else {
            lines.push(`${index + 1}. ${formatUnknownItem(issue)}`)
          }
        })
      }

      const suggestions = report.suggestions || []
      if (suggestions.length > 0) {
        lines.push('整体建议：')
        suggestions.forEach((suggestion, index) => {
          lines.push(`${index + 1}. ${formatUnknownItem(suggestion)}`)
        })
      }

      return lines.length > 1 ? lines.join('\n') : ''
    })
    .filter(Boolean)
    .join('\n\n')
}

const buildCharacterDefinitions = (characters: NovelWriteCharacter[]) => {
  const selected = characters.filter((character) => character.selected)
  return selected.length > 0
    ? selected.map((character) => character.definition).join('\n\n')
    : '暂无人物定义'
}

const buildSceneContext = (scenes: NovelWriteScene[]) => {
  const selected = scenes.filter((scene) => scene.selected)
  return selected.length > 0
    ? selected.map((scene) => scene.definition).join('\n\n')
    : '暂无场景信息'
}

const SCENE_ORDER_UPDATED_EVENT = 'scene-order-updated'

let toastId = 0

export const NovelContent: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const {
    outlines,
    currentOutline,
    currentTree: outlineTree,
    fetchOutlines,
    fetchTree,
  } = useOutlineStore()
  const [loadedOutlineId, setLoadedOutlineId] = useState<string | null>(null)
  const [chapters, setChapters] = useState<ChapterItem[]>([])
  const [selectedChapter, setSelectedChapter] = useState<ChapterItem | null>(
    null
  )
  const [editContent, setEditContent] = useState('')
  const [generating, setGenerating] = useState(false)
  const [saving, setSaving] = useState(false)
  const [writeContext, setWriteContext] = useState<NovelWriteContext | null>(
    null
  )
  const [showWriteContext, setShowWriteContext] = useState(false)
  const [showPolishModal, setShowPolishModal] = useState(false)
  const [polishSuggestions, setPolishSuggestions] = useState('')
  const [contextLoading, setContextLoading] = useState(false)
  const [polishing, setPolishing] = useState(false)
  const [importingPolishSuggestions, setImportingPolishSuggestions] =
    useState(false)
  const [summarizingPreviousContext, setSummarizingPreviousContext] =
    useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [expandedVolumes, setExpandedVolumes] = useState<Set<string>>(
    new Set()
  )
  const autoSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showToast = useCallback((type: ToastType, message: string) => {
    const id = ++toastId
    setToasts((prev) => [...prev, { id, type, message }])
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 3000)
  }, [])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false

    const loadInitialData = async () => {
      try {
        await fetchOutlines(projectId)
      } catch {
        console.error('Failed to load outlines')
      }

      try {
        const result = (await chapterApi.list(projectId)) as unknown as {
          data: ChapterItem[]
        }
        if (!cancelled) {
          setChapters(result.data || [])
        }
      } catch {
        console.error('Failed to load chapters')
      }
    }

    void loadInitialData()
    return () => {
      cancelled = true
    }
  }, [projectId, fetchOutlines])

  useEffect(() => {
    if (!projectId || outlines.length === 0) return
    const currentOutlineAvailable =
      !!currentOutline &&
      currentOutline.project_id === projectId &&
      outlines.some((outline) => outline.id === currentOutline.id)
    if (currentOutlineAvailable) {
      setLoadedOutlineId(currentOutline.id)
      return
    }

    const firstOutlineId = outlines[0].id
    if (loadedOutlineId === firstOutlineId) return
    setLoadedOutlineId(firstOutlineId)
    fetchTree(projectId, firstOutlineId).catch(() => {
      console.error('Failed to load outline tree')
      setLoadedOutlineId(null)
    })
  }, [
    projectId,
    outlines,
    currentOutline,
    loadedOutlineId,
    fetchTree,
  ])

  const resetChapterSelection = useCallback(() => {
    setSelectedChapter(null)
    setEditContent('')
    setWriteContext(null)
    setPolishSuggestions('')
    setShowPolishModal(false)
  }, [])

  const handleSelectOutline = async (outlineId: string) => {
    if (!projectId || !outlineId) return
    try {
      setLoadedOutlineId(outlineId)
      await fetchTree(projectId, outlineId)
      setExpandedVolumes(new Set())
      resetChapterSelection()
    } catch {
      setLoadedOutlineId(null)
      showToast('error', '加载大纲失败')
    }
  }

  useEffect(() => {
    if (!projectId) return

    const handleSceneOrderUpdated = (event: Event) => {
      const detail = (event as CustomEvent<SceneOrderUpdatedDetail>).detail
      if (!detail || detail.projectId !== projectId) return

      const orderMap = new Map(
        detail.scenes.map((scene, index) => [scene.id, index])
      )
      setWriteContext((prev) => {
        if (!prev?.scenes) return prev
        const scenes = [...prev.scenes].sort((a, b) => {
          const aOrder = orderMap.get(a.id) ?? Number.MAX_SAFE_INTEGER
          const bOrder = orderMap.get(b.id) ?? Number.MAX_SAFE_INTEGER
          if (aOrder !== bOrder) return aOrder - bOrder
          return prev.scenes!.findIndex((scene) => scene.id === a.id) -
            prev.scenes!.findIndex((scene) => scene.id === b.id)
        })
        return {
          ...prev,
          scenes,
          scene_context: buildSceneContext(scenes),
        }
      })
    }

    window.addEventListener(SCENE_ORDER_UPDATED_EVENT, handleSceneOrderUpdated)
    return () => {
      window.removeEventListener(
        SCENE_ORDER_UPDATED_EVENT,
        handleSceneOrderUpdated
      )
    }
  }, [projectId])

  const selectChapter = async (chapter: ChapterItem) => {
    if (!projectId) return
    try {
      const detail = (await chapterApi.get(
        projectId,
        chapter.id
      )) as unknown as ChapterItem
      setSelectedChapter(detail)
      setEditContent(detail.content || '')
      setWriteContext(null)
      setPolishSuggestions('')
      setShowPolishModal(false)
    } catch {
      showToast('error', '加载章节失败')
    }
  }

  const updateChapterContentState = useCallback(
    (chapterId: string, content: string, wordCount: number) => {
      setSelectedChapter((prev) =>
        prev?.id === chapterId
          ? { ...prev, content, word_count: wordCount }
          : prev
      )
      setChapters((prev) =>
        prev.map((chapter) =>
          chapter.id === chapterId
            ? { ...chapter, content, word_count: wordCount }
            : chapter
        )
      )
    },
    []
  )

  const handleSave = async () => {
    if (!projectId || !selectedChapter) return
    setSaving(true)
    try {
      const cnChars = (editContent.match(/[\u4e00-\u9fff]/g) || []).length
      await chapterApi.update(projectId, selectedChapter.id, {
        content: editContent,
        word_count: cnChars,
      })
      updateChapterContentState(selectedChapter.id, editContent, cnChars)
      showToast('success', '保存成功')
    } catch {
      showToast('error', '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const scheduleAutoSave = useCallback(
    (content: string) => {
      if (autoSaveTimer.current) clearTimeout(autoSaveTimer.current)
      autoSaveTimer.current = setTimeout(async () => {
        if (!projectId || !selectedChapter) return
        try {
          const cnChars = (content.match(/[\u4e00-\u9fff]/g) || []).length
          await chapterApi.update(projectId, selectedChapter.id, {
            content,
            word_count: cnChars,
          })
          updateChapterContentState(selectedChapter.id, content, cnChars)
        } catch {
          // Auto-save failures are intentionally silent.
        }
      }, 5000)
    },
    [projectId, selectedChapter, updateChapterContentState]
  )

  const handleContentChange = (value: string) => {
    setEditContent(value)
    scheduleAutoSave(value)
  }

  const loadWriteContext = async (openPreview = false) => {
    if (!projectId || !selectedChapter) return
    if (openPreview) setShowWriteContext(true)
    setContextLoading(true)
    try {
      const result = (await chapterApi.getNovelWriteContext(
        projectId,
        selectedChapter.id
      )) as unknown as NovelWriteContext
      setWriteContext({
        ...result,
        character_definitions: result.characters?.length
          ? buildCharacterDefinitions(result.characters)
          : result.character_definitions,
        scene_context: result.scenes?.length
          ? buildSceneContext(result.scenes)
          : result.scene_context,
      })
    } catch {
      showToast('error', '加载 AI 输入失败')
    } finally {
      setContextLoading(false)
    }
  }

  const updateWriteContext = (
    key: EditableNovelWriteContextKey,
    value: string
  ) => {
    setWriteContext((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const updateCharacterSelection = (characterId: string, selected: boolean) => {
    setWriteContext((prev) => {
      if (!prev?.characters) return prev
      const characters = prev.characters.map((character) =>
        character.id === characterId ? { ...character, selected } : character
      )
      return {
        ...prev,
        characters,
        character_definitions: buildCharacterDefinitions(characters),
      }
    })
  }

  const setAllCharactersSelected = (selected: boolean) => {
    setWriteContext((prev) => {
      if (!prev?.characters) return prev
      const characters = prev.characters.map((character) => ({
        ...character,
        selected,
      }))
      return {
        ...prev,
        characters,
        character_definitions: buildCharacterDefinitions(characters),
      }
    })
  }

  const updateSceneSelection = (sceneId: string, selected: boolean) => {
    setWriteContext((prev) => {
      if (!prev?.scenes) return prev
      const scenes = prev.scenes.map((scene) =>
        scene.id === sceneId ? { ...scene, selected } : scene
      )
      return {
        ...prev,
        scenes,
        scene_context: buildSceneContext(scenes),
      }
    })
  }

  const setAllScenesSelected = (selected: boolean) => {
    setWriteContext((prev) => {
      if (!prev?.scenes) return prev
      const scenes = prev.scenes.map((scene) => ({
        ...scene,
        selected,
      }))
      return {
        ...prev,
        scenes,
        scene_context: buildSceneContext(scenes),
      }
    })
  }

  const buildWriteContextPayload = () => {
    if (!writeContext) return null
    return {
      outline_context: writeContext.outline_context,
      volume_context: writeContext.volume_context,
      chapter_title: writeContext.chapter_title,
      chapter_summary: writeContext.chapter_summary,
      character_definitions: writeContext.character_definitions,
      scene_context: writeContext.scene_context,
      previous_context: writeContext.previous_context,
      previous_chapter_content: writeContext.previous_chapter_content,
      style_requirements: writeContext.style_requirements,
    }
  }

  const handleSummarizePreviousContext = async () => {
    if (!projectId || !selectedChapter) return
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId) {
      showToast('error', '请先配置 LLM')
      return
    }
    setSummarizingPreviousContext(true)
    try {
      const result =
        (await chapterApi.summarizeNovelWritePreviousContext(
          projectId,
          selectedChapter.id,
          cfgId,
          writeContext?.style_requirements
        )) as unknown as {
          previous_context: string
          chapter_count: number
        }
      setWriteContext((prev) =>
        prev
          ? {
              ...prev,
              previous_context:
                result.previous_context || prev.previous_context,
            }
          : prev
      )
      showToast(
        'success',
        result.chapter_count > 0
          ? `已总结 ${result.chapter_count} 章前文背景`
          : '当前卷暂无可总结的前文'
      )
    } catch {
      showToast('error', 'AI 总结前文背景失败，请稍后重试')
    } finally {
      setSummarizingPreviousContext(false)
    }
  }

  const handleAIWriteStream = async () => {
    if (!projectId || !selectedChapter) return
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId) {
      showToast('error', '请先配置 LLM')
      return
    }
    if (autoSaveTimer.current) {
      clearTimeout(autoSaveTimer.current)
      autoSaveTimer.current = null
    }
    setGenerating(true)
    setEditContent('')
    const previousContent = editContent
    let fullContent = ''
    try {
      const resp = await fetch(
        `/api/v1/projects/${projectId}/chapters/${selectedChapter.id}/novel-write-stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            llm_config_id: cfgId,
            write_context: buildWriteContextPayload(),
          }),
        }
      )
      if (!resp.ok) {
        throw new Error(`AI 编写请求失败（${resp.status}）`)
      }
      const reader = resp.body?.getReader()
      if (!reader) throw new Error('AI 编写响应不可读取')
      const decoder = new TextDecoder()
      let buffer = ''
      let doneWordCount: number | null = null

      const handleSseLine = (rawLine: string) => {
        const line = rawLine.trimEnd()
        if (!line.startsWith('data: ')) return

        const data = line.slice(6)
        if (!data || data === '{}' || data === '[DONE]') return

        const parsed = JSON.parse(data)
        if (parsed.error) {
          throw new Error(parsed.error)
        }
        if (typeof parsed.content === 'string' && parsed.content.length > 0) {
          fullContent += parsed.content
          setEditContent(fullContent)
        }
        if (typeof parsed.word_count === 'number') {
          doneWordCount = parsed.word_count
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          handleSseLine(line)
        }
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        handleSseLine(buffer)
      }

      if (!fullContent.trim()) {
        throw new Error('AI 编写未返回正文')
      }

      const cnChars =
        doneWordCount ?? (fullContent.match(/[\u4e00-\u9fff]/g) || []).length
      updateChapterContentState(selectedChapter.id, fullContent, cnChars)
      showToast('success', `AI 编写完成，共 ${cnChars} 字`)
    } catch (error) {
      if (!fullContent) {
        setEditContent(previousContent)
      }
      showToast(
        'error',
        error instanceof Error
          ? error.message
          : 'AI 编写失败，请检查 LLM 配置后重试'
      )
    } finally {
      setGenerating(false)
    }
  }

  const handleImportPolishSuggestions = async () => {
    if (!projectId || !selectedChapter) return
    setImportingPolishSuggestions(true)
    try {
      const result = (await analysisApi.getReports(
        projectId,
        selectedChapter.id
      )) as unknown as { data: AnalysisReportItem[] }
      const imported = formatAnalysisReportsForPolish(result.data || [])
      if (!imported.trim()) {
        showToast('error', '当前章节暂无可导入的一致性分析建议')
        return
      }
      setPolishSuggestions(imported)
      showToast('success', '已导入一致性分析建议')
    } catch {
      showToast('error', '导入一致性分析建议失败')
    } finally {
      setImportingPolishSuggestions(false)
    }
  }

  const handleOpenPolishModal = () => {
    if (!editContent.trim()) {
      showToast('error', '当前章节暂无可打磨内容')
      return
    }
    setShowPolishModal(true)
  }

  const handleAIPolish = async () => {
    if (!projectId || !selectedChapter) return
    if (!editContent.trim()) {
      showToast('error', '当前章节暂无可打磨内容')
      return
    }
    if (!polishSuggestions.trim()) {
      showToast('error', '请先填写打磨建议或导入一致性分析')
      return
    }
    const cfgId = await getActiveLLMConfigId()
    if (!cfgId) {
      showToast('error', '请先配置 LLM')
      return
    }

    if (autoSaveTimer.current) {
      clearTimeout(autoSaveTimer.current)
      autoSaveTimer.current = null
    }

    setPolishing(true)
    setShowPolishModal(false)
    const previousContent = editContent
    const sourceContent = editContent
    let fullContent = ''
    let streamDone = false
    setEditContent('')
    try {
      const resp = await fetch(
        `/api/v1/projects/${projectId}/chapters/${selectedChapter.id}/novel-polish-stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            llm_config_id: cfgId,
            chapter_content: sourceContent,
            polish_suggestions: polishSuggestions,
          }),
        }
      )
      if (!resp.ok) {
        throw new Error(`AI 打磨请求失败（${resp.status}）`)
      }
      const reader = resp.body?.getReader()
      if (!reader) throw new Error('AI 打磨响应不可读取')
      const decoder = new TextDecoder()
      let buffer = ''
      let doneWordCount: number | null = null

      const handleSseLine = (rawLine: string) => {
        const line = rawLine.trimEnd()
        if (!line.startsWith('data: ')) return

        const data = line.slice(6)
        if (!data || data === '{}' || data === '[DONE]') return

        const parsed = JSON.parse(data)
        if (parsed.error) {
          throw new Error(parsed.error)
        }
        if (typeof parsed.content === 'string' && parsed.content.length > 0) {
          fullContent += parsed.content
          setEditContent(fullContent)
        }
        if (typeof parsed.word_count === 'number') {
          doneWordCount = parsed.word_count
          streamDone = true
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          handleSseLine(line)
        }
      }
      buffer += decoder.decode()
      if (buffer.trim()) {
        handleSseLine(buffer)
      }

      if (!fullContent.trim()) {
        throw new Error('AI 打磨未返回正文')
      }
      if (!streamDone) {
        throw new Error('AI 打磨未正常完成，请稍后重试')
      }

      const cnChars =
        doneWordCount ?? (fullContent.match(/[\u4e00-\u9fff]/g) || []).length
      updateChapterContentState(selectedChapter.id, fullContent, cnChars)
      showToast('success', `AI 打磨完成，共 ${cnChars} 字`)
    } catch (error) {
      if (!streamDone) {
        setEditContent(previousContent)
      }
      showToast(
        'error',
        error instanceof Error
          ? error.message
          : 'AI 打磨失败，请检查 LLM 配置后重试'
      )
    } finally {
      setPolishing(false)
    }
  }

  const ensureChapter = async (node: OutlineNode) => {
    if (!projectId) return
    const existing = chapters.find(
      (c) => c.outline_node_id === node.id
    )
    if (existing) {
      await selectChapter(existing)
      return
    }
    try {
      const created = (await chapterApi.create(projectId, {
        outline_node_id: node.id,
        title: node.title,
        content: null,
        sort_order: node.sort_order,
      })) as unknown as ChapterItem
      setChapters((prev) => [...prev, created])
      await selectChapter(created)
    } catch {
      showToast('error', '创建章节失败')
    }
  }

  const toggleVolume = (volumeId: string) => {
    setExpandedVolumes((prev) => {
      const next = new Set(prev)
      if (next.has(volumeId)) next.delete(volumeId)
      else next.add(volumeId)
      return next
    })
  }

  const cnCharCount = (editContent.match(/[\u4e00-\u9fff]/g) || []).length

  return (
    <div className="flex h-full">
      <div className="flex w-64 flex-col border-r bg-white">
        <div className="border-b p-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-gray-700">
            <BookOpen className="h-4 w-4" /> 章节导航
          </h3>
          {outlines.length > 0 && (
            <div className="mt-3">
              <label className="block text-xs font-medium text-gray-500">
                当前大纲
              </label>
              <select
                className="mt-1 w-full rounded-md border px-2 py-1.5 text-sm text-gray-700"
                value={currentOutline?.id || ''}
                onChange={(e) => handleSelectOutline(e.target.value)}
              >
                {outlines.map((outline) => (
                  <option key={outline.id} value={outline.id}>
                    {outline.title}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        <div className="flex-1 overflow-auto p-2">
          {outlineTree.length === 0 ? (
            <p className="p-2 text-sm text-gray-400">请先创建大纲</p>
          ) : (
            outlineTree.map((volume) => (
              <div key={volume.id} className="mb-1">
                <button
                  onClick={() => toggleVolume(volume.id)}
                  className="flex w-full items-center gap-1.5 rounded px-2 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
                >
                  {expandedVolumes.has(volume.id) ? (
                    <ChevronDown className="h-3.5 w-3.5 text-gray-400" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 text-gray-400" />
                  )}
                  <span className="truncate">{volume.title}</span>
                </button>
                {expandedVolumes.has(volume.id) &&
                  volume.children
                    ?.filter((c) => c.node_type === 'CHAPTER')
                    .map((chapterNode) => {
                      const chapter = chapters.find(
                        (c) => c.outline_node_id === chapterNode.id
                      )
                      const isActive =
                        selectedChapter?.outline_node_id === chapterNode.id
                      return (
                        <button
                          key={chapterNode.id}
                          onClick={() => ensureChapter(chapterNode)}
                          className={`flex w-full items-center gap-1.5 rounded px-2 py-1.5 pl-7 text-sm transition-colors ${
                            isActive
                              ? 'bg-blue-50 text-blue-600 font-medium'
                              : 'text-gray-600 hover:bg-gray-50'
                          }`}
                        >
                          <span className="truncate">
                            {chapterNode.title}
                          </span>
                          {chapter?.content && (
                            <span className="ml-auto text-xs text-gray-400">
                              {chapter.word_count}字
                            </span>
                          )}
                        </button>
                      )
                    })}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col">
        {selectedChapter ? (
          <>
            <div className="flex items-center justify-between border-b px-4 py-2">
              <div className="flex items-center gap-3">
                <div className="min-w-0">
                  {currentOutline && (
                    <div className="truncate text-xs text-gray-400">
                      大纲：{currentOutline.title}
                    </div>
                  )}
                  <h3 className="truncate font-semibold text-gray-800">
                    {selectedChapter.title}
                  </h3>
                </div>
                <span className="text-sm text-gray-400">
                  {cnCharCount} 字
                </span>
                {saving && (
                  <span className="text-xs text-gray-400">保存中...</span>
                )}
                {!saving && editContent && (
                  <span className="text-xs text-green-500">已自动保存</span>
                )}
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSave}
                  disabled={saving || polishing}
                >
                  <Save className="mr-1 h-4 w-4" /> 保存
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => loadWriteContext(true)}
                  disabled={contextLoading || generating || polishing}
                >
                  {contextLoading ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <FileText className="mr-1 h-4 w-4" />
                  )}
                  AI 输入
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleOpenPolishModal}
                  disabled={generating || polishing || !editContent.trim()}
                >
                  {polishing ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="mr-1 h-4 w-4" />
                  )}
                  AI 打磨
                </Button>
                <Button
                  size="sm"
                  onClick={handleAIWriteStream}
                  disabled={generating || polishing}
                >
                  {generating ? (
                    <>
                      <Loader2 className="mr-1 h-4 w-4 animate-spin" />{' '}
                      AI 编写中...
                    </>
                  ) : (
                    <>
                      <Sparkles className="mr-1 h-4 w-4" /> AI 编写
                    </>
                  )}
                </Button>
                {selectedChapter.content && !generating && !polishing && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleAIWriteStream}
                  >
                    <RefreshCw className="mr-1 h-4 w-4" /> 重新生成
                  </Button>
                )}
              </div>
            </div>
            <div className="flex-1 overflow-auto">
              {generating || polishing ? (
                <div className="mx-auto max-w-3xl p-8">
                  <div className="mb-4 flex items-center gap-2 text-blue-500">
                    <Loader2 className="h-5 w-5 animate-spin" />
                    <span className="text-sm">
                      {polishing ? 'AI 正在打磨章节内容...' : 'AI 正在编写章节内容...'}
                    </span>
                  </div>
                  <div className="whitespace-pre-wrap text-base leading-relaxed text-gray-800">
                    {editContent}
                    <span className="animate-pulse text-blue-500">▌</span>
                  </div>
                </div>
              ) : (
                <textarea
                  className="h-full w-full resize-none p-8 text-base leading-relaxed text-gray-800 focus:outline-none"
                  value={editContent}
                  onChange={(e) => handleContentChange(e.target.value)}
                  placeholder="点击「AI 编写」生成章节内容，或直接在此输入..."
                  style={{ minHeight: '100%' }}
                />
              )}
            </div>
          </>
        ) : (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <BookOpen className="mx-auto mb-4 h-16 w-16 text-gray-300" />
              <p className="text-gray-500">请从左侧选择章节开始阅读或编写</p>
              <p className="mt-1 text-sm text-gray-400">
                展开卷目录，点击章节名称进入
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto flex items-center gap-2 rounded-lg px-4 py-2 text-sm shadow-lg transition-all ${
              t.type === 'success'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-red-50 text-red-700 border border-red-200'
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>

      <Modal
        open={showWriteContext}
        onClose={() => setShowWriteContext(false)}
        title="AI 编写输入"
      >
        <div className="max-h-[70vh] space-y-4 overflow-auto pr-1">
          {contextLoading ? (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中...
            </div>
          ) : writeContext ? (
            <>
              <div>
                <div className="mb-1 text-xs font-medium text-gray-500">
                  大纲信息
                  {writeContext.outline_title
                    ? `：${writeContext.outline_title}`
                    : ''}
                </div>
                <textarea
                  className="w-full resize-y rounded border p-2 text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={4}
                  value={writeContext.outline_context}
                  onChange={(e) =>
                    updateWriteContext('outline_context', e.target.value)
                  }
                />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-gray-500">
                  卷信息
                  {writeContext.volume_title
                    ? `：${writeContext.volume_title}`
                    : ''}
                </div>
                <textarea
                  className="w-full resize-y rounded border p-2 text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={4}
                  value={writeContext.volume_context}
                  onChange={(e) =>
                    updateWriteContext('volume_context', e.target.value)
                  }
                />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-gray-500">
                  章节标题
                </div>
                <input
                  className="w-full rounded border p-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  value={writeContext.chapter_title}
                  onChange={(e) =>
                    updateWriteContext('chapter_title', e.target.value)
                  }
                />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-gray-500">
                  章节摘要
                </div>
                <textarea
                  className="w-full resize-y rounded border p-2 text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={5}
                  value={writeContext.chapter_summary}
                  onChange={(e) =>
                    updateWriteContext('chapter_summary', e.target.value)
                  }
                />
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-xs font-medium text-gray-500">
                    人物设定（
                    {writeContext.characters
                      ? writeContext.characters.filter((c) => c.selected).length
                      : writeContext.character_count}
                    /{writeContext.character_count}）
                  </div>
                  {writeContext.characters && writeContext.characters.length > 0 && (
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setAllCharactersSelected(true)}
                      >
                        全选
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setAllCharactersSelected(false)}
                      >
                        清空
                      </Button>
                    </div>
                  )}
                </div>
                {writeContext.characters && writeContext.characters.length > 0 ? (
                  <div className="grid max-h-72 gap-2 overflow-auto rounded border bg-gray-50 p-2 sm:grid-cols-2">
                    {writeContext.characters.map((character) => (
                      <button
                        key={character.id}
                        type="button"
                        onClick={() =>
                          updateCharacterSelection(
                            character.id,
                            !character.selected
                          )
                        }
                        className={`rounded-md border p-3 text-left transition-colors ${
                          character.selected
                            ? 'border-blue-300 bg-white ring-1 ring-blue-100'
                            : 'border-gray-200 bg-gray-100 text-gray-400'
                        }`}
                      >
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-gray-800">
                              {character.name}
                            </div>
                            {character.aliases?.length > 0 && (
                              <div className="truncate text-xs text-gray-400">
                                {character.aliases.join('、')}
                              </div>
                            )}
                          </div>
                          <span
                            className={`shrink-0 rounded px-2 py-0.5 text-xs ${
                              character.selected
                                ? 'bg-blue-100 text-blue-700'
                                : 'bg-gray-200 text-gray-500'
                            }`}
                          >
                            {character.selected ? '已加入' : '未加入'}
                          </span>
                        </div>
                        <div className="line-clamp-4 whitespace-pre-wrap text-xs leading-relaxed text-gray-500">
                          {character.definition}
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <textarea
                    className="w-full resize-y rounded border p-2 text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    rows={7}
                    value={writeContext.character_definitions}
                    onChange={(e) =>
                      updateWriteContext(
                        'character_definitions',
                        e.target.value
                      )
                    }
                  />
                )}
              </div>
              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="text-xs font-medium text-gray-500">
                    场景信息（
                    {writeContext.scenes
                      ? writeContext.scenes.filter((scene) => scene.selected)
                          .length
                      : 0}
                    /{writeContext.scene_count}）
                  </div>
                  {writeContext.scenes && writeContext.scenes.length > 0 && (
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setAllScenesSelected(true)}
                      >
                        全部加入
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setAllScenesSelected(false)}
                      >
                        清空
                      </Button>
                    </div>
                  )}
                </div>
                {writeContext.scenes && writeContext.scenes.length > 0 ? (
                  <div className="grid max-h-72 gap-2 overflow-auto rounded border bg-gray-50 p-2 sm:grid-cols-2">
                    {writeContext.scenes.map((scene) => (
                      <button
                        key={scene.id}
                        type="button"
                        onClick={() =>
                          updateSceneSelection(scene.id, !scene.selected)
                        }
                        className={`rounded-md border p-3 text-left transition-colors ${
                          scene.selected
                            ? 'border-emerald-300 bg-white ring-1 ring-emerald-100'
                            : 'border-gray-200 bg-gray-100 text-gray-400'
                        }`}
                      >
                        <div className="mb-2 flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-gray-800">
                              {scene.name}
                            </div>
                          </div>
                          <span
                            className={`shrink-0 rounded px-2 py-0.5 text-xs ${
                              scene.selected
                                ? 'bg-emerald-100 text-emerald-700'
                                : 'bg-gray-200 text-gray-500'
                            }`}
                          >
                            {scene.selected ? '已加入' : '未加入'}
                          </span>
                        </div>
                        <div className="line-clamp-4 whitespace-pre-wrap text-xs leading-relaxed text-gray-500">
                          {scene.definition}
                        </div>
                      </button>
                    ))}
                  </div>
                ) : (
                  <textarea
                    className="w-full resize-y rounded border p-2 text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    rows={5}
                    value={writeContext.scene_context}
                    onChange={(e) =>
                      updateWriteContext('scene_context', e.target.value)
                    }
                  />
                )}
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <div className="text-xs font-medium text-gray-500">
                    前文背景
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleSummarizePreviousContext}
                    disabled={summarizingPreviousContext || generating}
                  >
                    {summarizingPreviousContext ? (
                      <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                    ) : (
                      <Sparkles className="mr-1 h-4 w-4" />
                    )}
                    AI 总结前文背景
                  </Button>
                </div>
                <textarea
                  className="w-full resize-y rounded border p-2 text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={7}
                  value={writeContext.previous_context}
                  onChange={(e) =>
                    updateWriteContext('previous_context', e.target.value)
                  }
                />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-gray-500">
                  前一章内容
                  {writeContext.previous_chapter_title
                    ? `：${writeContext.previous_chapter_title}`
                    : ''}
                </div>
                <textarea
                  className="w-full resize-y rounded border p-2 text-xs leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={8}
                  value={writeContext.previous_chapter_content}
                  onChange={(e) =>
                    updateWriteContext(
                      'previous_chapter_content',
                      e.target.value
                    )
                  }
                />
              </div>
              <div>
                <div className="mb-1 text-xs font-medium text-gray-500">
                  文风要求
                </div>
                <textarea
                  className="w-full resize-y rounded border p-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={3}
                  value={writeContext.style_requirements}
                  onChange={(e) =>
                    updateWriteContext('style_requirements', e.target.value)
                  }
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => loadWriteContext()}
                  disabled={contextLoading || generating}
                >
                  恢复默认
                </Button>
                <Button
                  size="sm"
                  onClick={() => {
                    setShowWriteContext(false)
                    handleAIWriteStream()
                  }}
                  disabled={generating}
                >
                  <Sparkles className="mr-1 h-4 w-4" />
                  AI 编写
                </Button>
              </div>
            </>
          ) : (
            <p className="text-sm text-gray-500">暂无可用输入</p>
          )}
        </div>
      </Modal>

      <Modal
        open={showPolishModal}
        onClose={() => setShowPolishModal(false)}
        title="AI 打磨"
      >
        <div className="max-h-[70vh] space-y-4 overflow-auto pr-1">
          <div>
            <div className="mb-2 flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-gray-500">
                打磨建议
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleImportPolishSuggestions}
                disabled={importingPolishSuggestions || polishing}
              >
                {importingPolishSuggestions ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <FileText className="mr-1 h-4 w-4" />
                )}
                从一致性分析导入
              </Button>
            </div>
            <textarea
              className="w-full resize-y rounded border p-2 text-sm leading-relaxed text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={12}
              value={polishSuggestions}
              onChange={(e) => setPolishSuggestions(e.target.value)}
              placeholder="打磨建议"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowPolishModal(false)}
              disabled={polishing}
            >
              取消
            </Button>
            <Button
              size="sm"
              onClick={handleAIPolish}
              disabled={polishing || !editContent.trim() || !polishSuggestions.trim()}
            >
              {polishing ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-1 h-4 w-4" />
              )}
              {polishing ? '打磨中...' : '开始打磨'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}
