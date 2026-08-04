import React, { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  AlertCircle,
  BookOpen,
  CheckCircle2,
  Circle,
  Loader2,
  PenLine,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { getActiveLLMConfigId, novelAgentApi } from '@/services/api'
import { useAgentInputDraftStore } from '@/stores/agentInputDraftStore'
import { refreshProjectOutlineData } from '@/stores/outlineStore'
import { useProjectStore } from '@/stores/projectStore'
import type {
  NovelAgentSession,
  NovelAgentStepResult,
  NovelAgentWriteResponse,
} from '@/types'
import { AgentSessionBar } from './AgentSessionBar'

const numberValue = (value: string, fallback: number) => {
  const parsed = Number.parseInt(value, 10)
  return Number.isFinite(parsed) ? parsed : fallback
}

type NovelAgentStreamEvent =
  | { type: 'session'; session: NovelAgentSession }
  | { type: 'steps'; steps: NovelAgentStepResult[] }
  | { type: 'step'; step: NovelAgentStepResult }
  | { type: 'plan'; plan: Record<string, unknown> }
  | { type: 'confirmation_required'; session: NovelAgentSession }
  | { type: 'result'; result: NovelAgentWriteResponse }
  | { type: 'done' }
  | { type: 'error'; error: string }

type BlueprintTitleNode = {
  title: string
  nodeType: string
  children: BlueprintTitleNode[]
}

type BlueprintPlanSummary = {
  projectTitle: string
  outlineTitle: string
  outlineNodes: BlueprintTitleNode[]
  characterNames: string[]
  sceneNames: string[]
}

const outlineNodeLabels: Record<string, string> = {
  VOLUME: '卷',
  CHAPTER: '章',
  SCENE: '场景',
  PLOT_POINT: '情节点',
  KEY_EVENT: '关键事件',
}

const recordValue = (value: unknown): Record<string, unknown> | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null

const textValue = (value: unknown): string =>
  typeof value === 'string' ? value.trim() : ''

const readNamedItems = (value: unknown): string[] => {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const name = textValue(recordValue(item)?.name)
    return name ? [name] : []
  })
}

const readOutlineTitleNodes = (value: unknown): BlueprintTitleNode[] => {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    const node = recordValue(item)
    if (!node) return []
    return [
      {
        title: textValue(node.title) || '未命名节点',
        nodeType: textValue(node.node_type),
        children: readOutlineTitleNodes(node.children),
      },
    ]
  })
}

const summarizeBlueprintPlan = (
  plan: Record<string, unknown>
): BlueprintPlanSummary => {
  const project = recordValue(plan.project)
  const outline = recordValue(plan.outline)
  return {
    projectTitle: textValue(project?.name) || '未命名项目',
    outlineTitle: textValue(outline?.title) || '未命名大纲',
    outlineNodes: readOutlineTitleNodes(outline?.children),
    characterNames: readNamedItems(plan.characters),
    sceneNames: readNamedItems(plan.scenes),
  }
}

const OutlineTitleList: React.FC<{ nodes: BlueprintTitleNode[] }> = ({
  nodes,
}) => (
  <div className="space-y-1.5">
    {nodes.map((node, index) => (
      <div key={`${index}:${node.nodeType}:${node.title}`}>
        <div className="flex items-center gap-2 rounded-md bg-white px-2.5 py-1.5 text-sm text-gray-800">
          <span className="shrink-0 rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-600">
            {outlineNodeLabels[node.nodeType] || '节点'}
          </span>
          <span className="min-w-0 truncate" title={node.title}>
            {node.title}
          </span>
        </div>
        {node.children.length > 0 && (
          <div className="ml-3 mt-1.5 border-l border-gray-200 pl-3">
            <OutlineTitleList nodes={node.children} />
          </div>
        )}
      </div>
    ))}
  </div>
)

export const NovelAgent: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { setCurrentProject, fetchProjects } = useProjectStore()
  const [idea, setIdea] = useState('')
  const [genre, setGenre] = useState('')
  const [styleRequirements, setStyleRequirements] = useState('')
  const [extraRequirements, setExtraRequirements] = useState('')
  const [volumeCount, setVolumeCount] = useState('3')
  const [chapterCount, setChapterCount] = useState('12')
  const [wordCountTarget, setWordCountTarget] = useState('300000')
  const [writeChapterCount, setWriteChapterCount] = useState('3')
  const [updateProject, setUpdateProject] = useState(true)
  const [useResponsesApi, setUseResponsesApi] = useState(true)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<NovelAgentWriteResponse | null>(null)
  const [steps, setSteps] = useState<NovelAgentStepResult[]>([])
  const [sessions, setSessions] = useState<NovelAgentSession[]>([])
  const [activeSession, setActiveSession] = useState<NovelAgentSession | null>(
    null
  )
  const agentInputDraft = useAgentInputDraftStore((state) => state.draft)
  const clearAgentInputDraft = useAgentInputDraftStore(
    (state) => state.clearDraft
  )
  const projectSessions = sessions.filter(
    (session) => session.project_id === projectId
  )
  const projectSession =
    activeSession?.project_id === projectId ? activeSession : null
  const importedIdeaDraft =
    agentInputDraft &&
    agentInputDraft.projectId === projectId &&
    agentInputDraft.target === 'generate'
      ? agentInputDraft
      : null
  const effectiveIdea = importedIdeaDraft?.content ?? idea

  const applySession = (session: NovelAgentSession | null) => {
    setActiveSession(session)
    setSteps(session?.steps || [])
    setError(session?.error_message || '')
    setResult(
      session?.result
        ? (session.result as unknown as NovelAgentWriteResponse)
        : null
    )
  }

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    void novelAgentApi
      .listSessions(projectId, 'generate')
      .then((response) => {
        if (cancelled) return
        const items = ((response as unknown as { data: NovelAgentSession[] })
          .data || [])
        setSessions(items)
        applySession(items[0] || null)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setError(
          caught instanceof Error ? caught.message : 'Agent 会话加载失败'
        )
      })
    return () => {
      cancelled = true
    }
  }, [projectId])

  const refreshSessions = async (preferredSessionId?: string) => {
    if (!projectId) return
    const response = (await novelAgentApi.listSessions(
      projectId,
      'generate'
    )) as unknown as { data: NovelAgentSession[] }
    const items = response.data || []
    setSessions(items)
    const selected = preferredSessionId
      ? items.find((session) => session.id === preferredSessionId)
      : projectSession
        ? items.find((session) => session.id === projectSession.id)
        : items[0]
    applySession(selected || items[0] || null)
  }

  const handleCreateSession = async () => {
    if (!projectId) return
    const session = (await novelAgentApi.createSession(
      projectId,
      'generate'
    )) as unknown as NovelAgentSession
    setSessions((current) => [session, ...current])
    applySession(session)
  }

  const handleSelectSession = (sessionId: string) => {
    const session = sessions.find((item) => item.id === sessionId) || null
    applySession(session)
  }

  const handleRenameSession = async (name: string) => {
    if (!projectId || !projectSession) return
    const updated = (await novelAgentApi.renameSession(
      projectId,
      projectSession.id,
      name
    )) as unknown as NovelAgentSession
    setSessions((current) =>
      current.map((session) => (session.id === updated.id ? updated : session))
    )
    setActiveSession(updated)
  }

  const handleDeleteSession = async () => {
    if (!projectId || !projectSession) return
    if (!window.confirm('只删除该 Agent 会话记录，已生成的项目内容会保留。继续吗？')) {
      return
    }
    await novelAgentApi.deleteSession(projectId, projectSession.id)
    const remaining = projectSessions.filter(
      (session) => session.id !== projectSession.id
    )
    setSessions(remaining)
    applySession(remaining[0] || null)
  }

  const updateStep = (nextStep: NovelAgentStepResult) => {
    setSteps((currentSteps) => {
      const existingIndex = currentSteps.findIndex(
        (step) => step.step === nextStep.step
      )
      if (existingIndex === -1) return [...currentSteps, nextStep]
      return currentSteps.map((step, index) =>
        index === existingIndex ? nextStep : step
      )
    })
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    const submittedIdea = effectiveIdea.trim()
    if (!projectId || !submittedIdea) return
    setLoading(true)
    setError('')
    setResult(null)
    setSteps([])
    let runSessionId = projectSession?.id || ''
    try {
      const llmConfigId = await getActiveLLMConfigId()
      if (!llmConfigId) {
        setError('请先在系统设置中配置并启用 LLM。')
        return
      }
      const requestBody = {
        session_id: projectSession?.id || null,
        llm_config_id: llmConfigId,
        idea: submittedIdea,
        genre: genre.trim() || null,
        style_requirements: styleRequirements.trim() || null,
        extra_requirements: extraRequirements.trim() || null,
        volume_count: numberValue(volumeCount, 3),
        chapter_count: numberValue(chapterCount, 12),
        word_count_target: numberValue(wordCountTarget, 300000),
        write_chapter_count: numberValue(writeChapterCount, 3),
        update_project: updateProject,
        use_deepseek_responses_api: useResponsesApi,
      }
      const response = await fetch(
        `/api/v1/projects/${projectId}/novel-agent/write-stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        }
      )
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(
          payload?.detail || `Agent 生成请求失败（${response.status}）`
        )
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('Agent 生成响应不可读取')

      const decoder = new TextDecoder()
      let buffer = ''
      let streamDone = false
      let confirmationReceived = false

      const handleSseLine = (rawLine: string) => {
        const line = rawLine.trimEnd()
        if (!line.startsWith('data: ')) return
        const data = line.slice(6)
        if (!data || data === '{}') return

        const streamEvent = JSON.parse(data) as NovelAgentStreamEvent
        if (streamEvent.type === 'session') {
          runSessionId = streamEvent.session.id
          setActiveSession(streamEvent.session)
          setSessions((current) => {
            const exists = current.some(
              (session) => session.id === streamEvent.session.id
            )
            return exists
              ? current.map((session) =>
                  session.id === streamEvent.session.id
                    ? streamEvent.session
                    : session
                )
              : [streamEvent.session, ...current]
          })
        } else if (streamEvent.type === 'steps') {
          setSteps(streamEvent.steps)
        } else if (streamEvent.type === 'step') {
          updateStep(streamEvent.step)
        } else if (streamEvent.type === 'plan') {
          setActiveSession((current) =>
            current ? { ...current, plan: streamEvent.plan } : current
          )
        } else if (streamEvent.type === 'confirmation_required') {
          confirmationReceived = true
          runSessionId = streamEvent.session.id
          setActiveSession(streamEvent.session)
          setSessions((current) =>
            current.map((session) =>
              session.id === streamEvent.session.id
                ? streamEvent.session
                : session
            )
          )
        } else if (streamEvent.type === 'done') {
          streamDone = true
        } else if (streamEvent.type === 'error') {
          throw new Error(streamEvent.error || 'Agent 生成失败')
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
      if (buffer.trim()) handleSseLine(buffer)

      if (!streamDone || !confirmationReceived) {
        throw new Error('Agent 计划生成流程未正常结束，请稍后重试')
      }
      await refreshSessions(runSessionId || undefined)
      if (importedIdeaDraft) {
        setIdea(submittedIdea)
        clearAgentInputDraft(importedIdeaDraft.id)
      }
    } catch (err: unknown) {
      const detail =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response
              ?.data?.detail
      const message = detail || 'Agent 生成失败，请稍后重试。'
      setError(message)
      setSteps((currentSteps) =>
        currentSteps.map((step) =>
          step.status === 'running'
            ? { ...step, status: 'failed', message }
            : step
        )
      )
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmExecution = async () => {
    if (
      !projectId ||
      !projectSession ||
      projectSession.status !== 'awaiting_confirmation' ||
      !projectSession.plan
    ) {
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const response = await fetch(
        `/api/v1/projects/${projectId}/novel-agent/write-execute-stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ session_id: projectSession.id }),
        }
      )
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(
          payload?.detail || `Agent 执行请求失败（${response.status}）`
        )
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('Agent 执行响应不可读取')
      const decoder = new TextDecoder()
      let buffer = ''
      let streamDone = false
      let finalResult: NovelAgentWriteResponse | null = null

      const handleSseLine = (rawLine: string) => {
        const line = rawLine.trimEnd()
        if (!line.startsWith('data: ')) return
        const data = line.slice(6)
        if (!data || data === '{}') return
        const streamEvent = JSON.parse(data) as NovelAgentStreamEvent
        if (streamEvent.type === 'session') {
          setActiveSession(streamEvent.session)
          setSessions((current) =>
            current.map((session) =>
              session.id === streamEvent.session.id
                ? streamEvent.session
                : session
            )
          )
        } else if (streamEvent.type === 'steps') {
          setSteps(streamEvent.steps)
        } else if (streamEvent.type === 'step') {
          updateStep(streamEvent.step)
        } else if (streamEvent.type === 'result') {
          finalResult = streamEvent.result
          setResult(streamEvent.result)
          setSteps(streamEvent.result.steps)
        } else if (streamEvent.type === 'done') {
          streamDone = true
        } else if (streamEvent.type === 'error') {
          throw new Error(streamEvent.error || 'Agent 执行失败')
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) handleSseLine(line)
      }
      buffer += decoder.decode()
      if (buffer.trim()) handleSseLine(buffer)

      const completedResult = finalResult as NovelAgentWriteResponse | null
      if (!streamDone || !completedResult) {
        throw new Error('Agent 执行流程未正常结束，请稍后重试')
      }
      setCurrentProject(completedResult.project)
      await Promise.all([
        fetchProjects(),
        refreshSessions(completedResult.session_id || undefined),
        refreshProjectOutlineData(projectId, completedResult.outline.id).catch(
          (caught: unknown) => {
            console.error('Failed to refresh Agent-generated outline', caught)
          }
        ),
      ])
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Agent 执行失败'
      setError(message)
      setSteps((currentSteps) =>
        currentSteps.map((step) =>
          step.status === 'running'
            ? { ...step, status: 'failed', message }
            : step
        )
      )
      try {
        await refreshSessions(projectSession.id)
      } catch {
        // Keep the streamed local state when session refresh fails.
      }
    } finally {
      setLoading(false)
    }
  }

  const writtenCount = result?.written_chapters.length || 0
  const firstWrittenChapter = result?.written_chapters[0]
  const completedStepCount = steps.filter(
    (step) => step.status === 'completed'
  ).length
  const activeStep = steps.find((step) => step.status === 'running')
  const planSummary = projectSession?.plan
    ? summarizeBlueprintPlan(projectSession.plan)
    : null

  return (
    <div className="min-h-full bg-gray-50 p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-blue-600">
              <Sparkles className="h-4 w-4" />
              Agent 生成
            </div>
            <h1 className="mt-1 text-2xl font-semibold text-gray-900">
              从想法生成长篇项目
            </h1>
          </div>
          {firstWrittenChapter && (
            <Button
              variant="outline"
              onClick={() =>
                navigate(`/projects/${projectId}/chapters/${firstWrittenChapter.id}`)
              }
              className="gap-2"
            >
              <BookOpen className="h-4 w-4" />
              打开首章
            </Button>
          )}
        </div>

        <AgentSessionBar
          sessions={projectSessions}
          activeSession={projectSession}
          busy={loading}
          onSelect={handleSelectSession}
          onCreate={() => void handleCreateSession()}
          onRename={handleRenameSession}
          onDelete={handleDeleteSession}
        />

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <form
            onSubmit={handleSubmit}
            className="rounded-md border bg-white p-5 shadow-sm"
          >
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  想法
                </label>
                <textarea
                  value={effectiveIdea}
                  onChange={(event) => {
                    if (importedIdeaDraft) {
                      clearAgentInputDraft(importedIdeaDraft.id)
                    }
                    setIdea(event.target.value)
                  }}
                  rows={9}
                  className="mt-1 w-full resize-y rounded-md border border-gray-300 px-3 py-2 text-sm leading-6 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="一个被迫接手旧书店的女孩，发现每本书都会改变现实中的一段记忆。"
                  disabled={loading}
                />
                {importedIdeaDraft && (
                  <p className="mt-1.5 text-xs text-blue-600">
                    已从小说讨论导入：{importedIdeaDraft.sourceTitle}
                  </p>
                )}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <Input
                  label="题材"
                  value={genre}
                  onChange={(event) => setGenre(event.target.value)}
                  placeholder="悬疑 / 都市 / 科幻"
                  disabled={loading}
                />
                <Input
                  label="目标总字数"
                  type="number"
                  min={10000}
                  max={5000000}
                  value={wordCountTarget}
                  onChange={(event) => setWordCountTarget(event.target.value)}
                  disabled={loading}
                />
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                <Input
                  label="卷数"
                  type="number"
                  min={1}
                  max={12}
                  value={volumeCount}
                  onChange={(event) => setVolumeCount(event.target.value)}
                  disabled={loading}
                />
                <Input
                  label="全书总章数"
                  type="number"
                  min={Math.max(1, numberValue(volumeCount, 1))}
                  max={100}
                  value={chapterCount}
                  onChange={(event) => setChapterCount(event.target.value)}
                  disabled={loading}
                />
                <Input
                  label="自动写作章数"
                  type="number"
                  min={0}
                  max={100}
                  value={writeChapterCount}
                  onChange={(event) => setWriteChapterCount(event.target.value)}
                  disabled={loading}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700">
                  文风
                </label>
                <textarea
                  value={styleRequirements}
                  onChange={(event) =>
                    setStyleRequirements(event.target.value)
                  }
                  rows={3}
                  className="mt-1 w-full resize-y rounded-md border border-gray-300 px-3 py-2 text-sm leading-6 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="冷静克制，细节真实，对白有潜台词。"
                  disabled={loading}
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700">
                  额外要求
                </label>
                <textarea
                  value={extraRequirements}
                  onChange={(event) =>
                    setExtraRequirements(event.target.value)
                  }
                  rows={3}
                  className="mt-1 w-full resize-y rounded-md border border-gray-300 px-3 py-2 text-sm leading-6 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="女主第一人称；结局开放；不要超自然万能解法。"
                  disabled={loading}
                />
              </div>

              <div className="flex flex-wrap gap-4 border-t pt-4">
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={updateProject}
                    onChange={(event) => setUpdateProject(event.target.checked)}
                    disabled={loading}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  更新项目信息
                </label>
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    checked={useResponsesApi}
                    onChange={(event) =>
                      setUseResponsesApi(event.target.checked)
                    }
                    disabled={loading}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  DeepSeek Responses
                </label>
              </div>

              {error && (
                <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              <Button
                type="submit"
                disabled={loading || !effectiveIdea.trim()}
                className="w-full gap-2"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <PenLine className="h-4 w-4" />
                )}
                {loading
                  ? activeStep
                    ? `${activeStep.label}中...`
                    : '正在生成计划...'
                  : '生成计划'}
              </Button>
            </div>
          </form>

          <aside className="space-y-4">
            <div className="rounded-md border bg-white p-4 shadow-sm">
              <h2 className="text-sm font-semibold text-gray-900">结果</h2>
              {result ? (
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-md bg-gray-50 p-3">
                    <div className="text-2xl font-semibold text-gray-900">
                      {result.chapters.length}
                    </div>
                    <div className="text-xs text-gray-500">章节</div>
                  </div>
                  <div className="rounded-md bg-gray-50 p-3">
                    <div className="text-2xl font-semibold text-gray-900">
                      {writtenCount}
                    </div>
                    <div className="text-xs text-gray-500">已写</div>
                  </div>
                  <div className="rounded-md bg-gray-50 p-3">
                    <div className="text-2xl font-semibold text-gray-900">
                      {result.characters.length}
                    </div>
                    <div className="text-xs text-gray-500">人物</div>
                  </div>
                  <div className="rounded-md bg-gray-50 p-3">
                    <div className="text-2xl font-semibold text-gray-900">
                      {result.scenes.length}
                    </div>
                    <div className="text-xs text-gray-500">场景</div>
                  </div>
                </div>
              ) : (
                <div className="mt-4 rounded-md bg-gray-50 p-3 text-sm text-gray-500">
                  等待生成
                </div>
              )}
            </div>

            <div className="rounded-md border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold text-gray-900">
                  执行步骤
                </h2>
                {steps.length > 0 && (
                  <span className="text-xs text-gray-500">
                    {completedStepCount}/{steps.length}
                  </span>
                )}
              </div>
              <div className="mt-3 space-y-2">
                {steps.map((step) => {
                  const hasProgress =
                    typeof step.current === 'number' &&
                    typeof step.total === 'number' &&
                    step.total > 0
                  const progress = hasProgress
                    ? Math.min(100, (step.current! / step.total!) * 100)
                    : 0
                  return (
                    <div
                      key={step.step}
                      className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm ${
                        step.status === 'running'
                          ? 'border-blue-200 bg-blue-50'
                          : step.status === 'failed'
                            ? 'border-red-200 bg-red-50'
                            : 'border-transparent bg-gray-50'
                      }`}
                    >
                      {step.status === 'completed' ? (
                        <CheckCircle2 className="mt-0.5 h-4 w-4 flex-shrink-0 text-green-600" />
                      ) : step.status === 'running' ? (
                        <Loader2 className="mt-0.5 h-4 w-4 flex-shrink-0 animate-spin text-blue-600" />
                      ) : step.status === 'failed' ? (
                        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0 text-red-600" />
                      ) : (
                        <Circle className="mt-0.5 h-4 w-4 flex-shrink-0 text-gray-300" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div
                          className={`font-medium ${
                            step.status === 'running'
                              ? 'text-blue-800'
                              : step.status === 'failed'
                                ? 'text-red-800'
                                : 'text-gray-800'
                          }`}
                        >
                          {step.label}
                        </div>
                        <div className="text-xs leading-5 text-gray-500">
                          {step.message}
                        </div>
                        {hasProgress && (
                          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-gray-200">
                            <div
                              className={`h-full rounded-full transition-all ${
                                step.status === 'failed'
                                  ? 'bg-red-500'
                                  : step.status === 'completed'
                                    ? 'bg-green-500'
                                    : 'bg-blue-500'
                              }`}
                              style={{ width: `${progress}%` }}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
                {steps.length === 0 && (
                  <div className="rounded-md bg-gray-50 px-3 py-2 text-sm text-gray-500">
                    {loading ? '正在连接 Agent 流程...' : '尚无步骤'}
                  </div>
                )}
              </div>
            </div>

            {projectSession?.plan && planSummary && (
              <div className="rounded-md border bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-semibold text-gray-900">
                    生成计划
                  </h2>
                  {projectSession.status === 'awaiting_confirmation' && (
                    <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-700">
                      等待确认
                    </span>
                  )}
                </div>
                <div className="mt-3 max-h-80 space-y-3 overflow-y-auto pr-1">
                  <div className="rounded-md bg-gray-50 p-3">
                    <div className="text-xs font-medium text-gray-500">项目</div>
                    <div className="mt-1 text-sm font-medium text-gray-900">
                      {planSummary.projectTitle}
                    </div>
                  </div>

                  <div className="rounded-md bg-gray-50 p-3">
                    <div className="text-xs font-medium text-gray-500">大纲</div>
                    <div className="mt-1 text-sm font-medium text-gray-900">
                      {planSummary.outlineTitle}
                    </div>
                    {planSummary.outlineNodes.length > 0 && (
                      <div className="mt-2">
                        <OutlineTitleList nodes={planSummary.outlineNodes} />
                      </div>
                    )}
                  </div>

                  {planSummary.characterNames.length > 0 && (
                    <div className="rounded-md bg-gray-50 p-3">
                      <div className="text-xs font-medium text-gray-500">
                        人物（{planSummary.characterNames.length}）
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {planSummary.characterNames.map((name, index) => (
                          <span
                            key={`${index}:${name}`}
                            className="rounded-full bg-white px-2 py-1 text-xs text-gray-700"
                          >
                            {name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {planSummary.sceneNames.length > 0 && (
                    <div className="rounded-md bg-gray-50 p-3">
                      <div className="text-xs font-medium text-gray-500">
                        场景（{planSummary.sceneNames.length}）
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {planSummary.sceneNames.map((name, index) => (
                          <span
                            key={`${index}:${name}`}
                            className="rounded-full bg-white px-2 py-1 text-xs text-gray-700"
                          >
                            {name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                {projectSession.status === 'awaiting_confirmation' && (
                  <Button
                    type="button"
                    onClick={() => void handleConfirmExecution()}
                    disabled={loading}
                    className="mt-3 w-full gap-2"
                  >
                    {loading ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <CheckCircle2 className="h-4 w-4" />
                    )}
                    确认计划并开始执行
                  </Button>
                )}
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}
