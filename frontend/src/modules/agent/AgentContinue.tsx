import React, { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  FilePenLine,
  Loader2,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { notifyChapterContentUpdated } from '@/events/chapterEvents'
import { getActiveLLMConfigId, novelAgentApi } from '@/services/api'
import { useAgentInputDraftStore } from '@/stores/agentInputDraftStore'
import { refreshProjectOutlineData } from '@/stores/outlineStore'
import type {
  NovelAgentContinueActionResult,
  NovelAgentContinuePlan,
  NovelAgentContinueRequestPayload,
  NovelAgentContinueResult,
  NovelAgentSession,
  NovelAgentStepResult,
} from '@/types'
import { AgentSessionBar } from './AgentSessionBar'

type ContinueStreamEvent =
  | { type: 'session'; session: NovelAgentSession }
  | { type: 'steps'; steps: NovelAgentStepResult[] }
  | { type: 'step'; step: NovelAgentStepResult }
  | { type: 'plan'; plan: NovelAgentContinuePlan }
  | { type: 'confirmation_required'; session: NovelAgentSession }
  | { type: 'action_result'; result: NovelAgentContinueActionResult }
  | { type: 'result'; result: NovelAgentContinueResult }
  | { type: 'done' }
  | { type: 'error'; error: string }

export const AgentContinue: React.FC = () => {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const [instruction, setInstruction] = useState('')
  const [styleRequirements, setStyleRequirements] = useState('')
  const [maxActions, setMaxActions] = useState('10')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [steps, setSteps] = useState<NovelAgentStepResult[]>([])
  const [result, setResult] = useState<NovelAgentContinueResult | null>(null)
  const [sessions, setSessions] = useState<NovelAgentSession[]>([])
  const [activeSession, setActiveSession] = useState<NovelAgentSession | null>(
    null
  )
  const agentInputDraft = useAgentInputDraftStore((state) => state.draft)
  const clearAgentInputDraft = useAgentInputDraftStore(
    (state) => state.clearDraft
  )
  const stepsContainerRef = useRef<HTMLDivElement>(null)
  const focusedStepRef = useRef<HTMLDivElement>(null)
  const projectSessions = sessions.filter(
    (session) => session.project_id === projectId
  )
  const projectSession =
    activeSession?.project_id === projectId ? activeSession : null
  const importedInstructionDraft =
    agentInputDraft &&
    agentInputDraft.projectId === projectId &&
    agentInputDraft.target === 'continue_edit'
      ? agentInputDraft
      : null
  const effectiveInstruction =
    importedInstructionDraft?.content ?? instruction

  const applySession = (session: NovelAgentSession | null) => {
    const requestPayload = session?.request_payload
      ? (session.request_payload as unknown as NovelAgentContinueRequestPayload)
      : null
    setActiveSession(session)
    setInstruction(requestPayload?.instruction || '')
    setStyleRequirements(requestPayload?.style_requirements || '')
    setMaxActions(
      typeof requestPayload?.max_actions === 'number'
        ? String(requestPayload.max_actions)
        : '10'
    )
    setSteps(session?.steps || [])
    setResult(
      session?.result
        ? (session.result as unknown as NovelAgentContinueResult)
        : null
    )
    setError(session?.error_message || '')
  }

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    void novelAgentApi
      .listSessions(projectId, 'continue_edit')
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
    const response = (await novelAgentApi.listSessions(
      projectId,
      'continue_edit'
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
    const session = (await novelAgentApi.createSession(
      projectId,
      'continue_edit'
    )) as unknown as NovelAgentSession
    setSessions((current) => [session, ...current])
    applySession(session)
  }

  const handleRenameSession = async (name: string) => {
    if (!projectSession) return
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
    if (!projectSession) return
    if (!window.confirm('只删除会话记录，已经修改的章节不会回滚。继续吗？')) {
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
    setSteps((current) => {
      const exists = current.some((step) => step.step === nextStep.step)
      return exists
        ? current.map((step) =>
            step.step === nextStep.step ? nextStep : step
          )
        : [...current, nextStep]
    })
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    const submittedInstruction = effectiveInstruction.trim()
    if (!submittedInstruction) return
    setLoading(true)
    setError('')
    setSteps([])
    setResult(null)
    let runSessionId = projectSession?.id || ''
    let streamStarted = false
    try {
      const llmConfigId = await getActiveLLMConfigId()
      if (!llmConfigId) throw new Error('请先在系统设置中配置并启用 LLM。')
      const response = await fetch(
        `/api/v1/projects/${projectId}/novel-agent/continue-stream`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: projectSession?.id || null,
            llm_config_id: llmConfigId,
            instruction: submittedInstruction,
            style_requirements: styleRequirements.trim() || null,
            max_actions: Number.parseInt(maxActions, 10) || 10,
          }),
        }
      )
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string
        } | null
        throw new Error(payload?.detail || `Agent 请求失败（${response.status}）`)
      }
      streamStarted = true
      const reader = response.body?.getReader()
      if (!reader) throw new Error('Agent 响应不可读取')
      const decoder = new TextDecoder()
      let buffer = ''
      let streamDone = false
      let confirmationReceived = false

      const handleSseLine = (rawLine: string) => {
        const line = rawLine.trimEnd()
        if (!line.startsWith('data: ')) return
        const data = line.slice(6)
        if (!data || data === '{}') return
        const streamEvent = JSON.parse(data) as ContinueStreamEvent
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
            current
              ? {
                  ...current,
                  plan: streamEvent.plan as unknown as Record<string, unknown>,
                }
              : current
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
          throw new Error(streamEvent.error || 'Agent 续写改编失败')
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
      if (!streamDone || !confirmationReceived) {
        throw new Error('Agent 续写改编计划生成流程未正常结束')
      }
      await refreshSessions(runSessionId)
      if (importedInstructionDraft) {
        setInstruction(submittedInstruction)
        clearAgentInputDraft(importedInstructionDraft.id)
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'Agent 续写改编失败'
      if (streamStarted && runSessionId) {
        try {
          await refreshSessions(runSessionId)
        } catch {
          // Keep the streamed local state when the persisted session cannot be reloaded.
        }
      }
      setError(message)
      setSteps((current) =>
        current.map((step) =>
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
      !projectSession ||
      projectSession.status !== 'awaiting_confirmation' ||
      !projectSession.plan
    ) {
      return
    }
    setLoading(true)
    setError('')
    setResult(null)
    let streamStarted = false
    try {
      const response = await fetch(
        `/api/v1/projects/${projectId}/novel-agent/continue-execute-stream`,
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
      streamStarted = true
      const reader = response.body?.getReader()
      if (!reader) throw new Error('Agent 执行响应不可读取')
      const decoder = new TextDecoder()
      let buffer = ''
      let streamDone = false
      let finalResult: NovelAgentContinueResult | null = null

      const handleSseLine = (rawLine: string) => {
        const line = rawLine.trimEnd()
        if (!line.startsWith('data: ')) return
        const data = line.slice(6)
        if (!data || data === '{}') return
        const streamEvent = JSON.parse(data) as ContinueStreamEvent
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
        } else if (streamEvent.type === 'action_result') {
          notifyChapterContentUpdated({
            projectId,
            chapterId: streamEvent.result.chapter_id,
            content: streamEvent.result.content,
            wordCount: streamEvent.result.word_count,
          })
          setResult((current) => ({
            session_id: current?.session_id || projectSession.id,
            summary: current?.summary || '',
            actions: [...(current?.actions || []), streamEvent.result],
          }))
        } else if (streamEvent.type === 'result') {
          finalResult = streamEvent.result
          setResult(streamEvent.result)
        } else if (streamEvent.type === 'done') {
          streamDone = true
        } else if (streamEvent.type === 'error') {
          throw new Error(streamEvent.error || 'Agent 续写改编执行失败')
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

      const completedResult = finalResult as NovelAgentContinueResult | null
      if (!streamDone || !completedResult) {
        throw new Error('Agent 续写改编执行流程未正常结束')
      }
      await Promise.all([
        refreshSessions(completedResult.session_id),
        refreshProjectOutlineData(projectId).catch((caught: unknown) => {
          console.error('Failed to refresh outline after Agent execution', caught)
        }),
      ])
    } catch (caught) {
      const message =
        caught instanceof Error ? caught.message : 'Agent 续写改编执行失败'
      if (streamStarted) {
        try {
          await refreshSessions(projectSession.id)
        } catch {
          // Keep the streamed local state when session refresh fails.
        }
      }
      setError(message)
      setSteps((current) =>
        current.map((step) =>
          step.status === 'running'
            ? { ...step, status: 'failed', message }
            : step
        )
      )
    } finally {
      setLoading(false)
    }
  }

  const completedCount = steps.filter(
    (step) => step.status === 'completed'
  ).length
  const currentPlan = projectSession?.plan
    ? (projectSession.plan as unknown as NovelAgentContinuePlan)
    : null
  const activeStep = steps.find((step) => step.status === 'running')
  const focusedStep =
    activeStep ||
    steps.find((step) => step.status === 'failed') ||
    steps.find((step) => step.status === 'pending') ||
    steps.at(-1)
  const focusedStepKey = focusedStep?.step

  useEffect(() => {
    const container = stepsContainerRef.current
    const target = focusedStepRef.current
    if (!container || !target) return
    container.scrollTop = target.offsetTop
  }, [focusedStepKey, projectSession?.id, steps.length])

  return (
    <div className="min-h-full bg-gray-50 p-6">
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium text-violet-600">
            <Sparkles className="h-4 w-4" />
            Agent 续写改编
          </div>
          <h1 className="mt-1 text-2xl font-semibold text-gray-900">
            先规划，再执行章节生成与打磨
          </h1>
        </div>

        <AgentSessionBar
          sessions={projectSessions}
          activeSession={projectSession}
          busy={loading}
          onSelect={(sessionId) =>
            applySession(
              projectSessions.find((session) => session.id === sessionId) || null
            )
          }
          onCreate={() => void handleCreateSession()}
          onRename={handleRenameSession}
          onDelete={handleDeleteSession}
        />

        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
          <form
            onSubmit={handleSubmit}
            className="rounded-md border bg-white p-5 shadow-sm"
          >
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700">
                  续写改编要求
                </label>
                <textarea
                  value={effectiveInstruction}
                  onChange={(event) => {
                    if (importedInstructionDraft) {
                      clearAgentInputDraft(importedInstructionDraft.id)
                    }
                    setInstruction(event.target.value)
                  }}
                  rows={12}
                  disabled={loading}
                  placeholder="例如：续写接下来的两个空章节；随后打磨上一章，让人物动机更自然，并加强章末悬念。"
                  className="mt-1 w-full resize-y rounded-md border px-3 py-2 text-sm leading-6 focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
                {importedInstructionDraft && (
                  <p className="mt-1.5 text-xs text-violet-600">
                    已从小说讨论导入：
                    {importedInstructionDraft.sourceTitle}
                  </p>
                )}
              </div>
              <div className="grid gap-4 md:grid-cols-[1fr_180px]">
                <Input
                  label="全局文风要求"
                  value={styleRequirements}
                  onChange={(event) => setStyleRequirements(event.target.value)}
                  disabled={loading}
                  placeholder="沿用原文风格"
                />
                <Input
                  label="最多执行动作"
                  type="number"
                  min={1}
                  max={50}
                  value={maxActions}
                  onChange={(event) => setMaxActions(event.target.value)}
                  disabled={loading}
                />
              </div>
              {error && (
                <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  <AlertCircle className="mt-0.5 h-4 w-4" />
                  {error}
                </div>
              )}
              <Button
                type="submit"
                disabled={loading || !effectiveInstruction.trim()}
                className="w-full gap-2"
              >
                {loading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <FilePenLine className="h-4 w-4" />
                )}
                {loading
                  ? activeStep
                    ? `${activeStep.label}中...`
                    : '正在生成 Plan...'
                  : '生成 Plan'}
              </Button>
            </div>
          </form>

          <aside className="space-y-4">
            <div className="rounded-md border bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between">
                <h2 className="text-sm font-semibold text-gray-900">执行步骤</h2>
                {steps.length > 0 && (
                  <span className="text-xs text-gray-500">
                    {completedCount}/{steps.length}
                  </span>
                )}
              </div>
              <div
                ref={stepsContainerRef}
                id="agent-continue-steps"
                aria-label="执行步骤列表"
                tabIndex={steps.length > 3 ? 0 : undefined}
                className="relative mt-3 max-h-[136px] space-y-2 overflow-y-auto pr-1"
              >
                {steps.map((step) => (
                  <div
                    key={step.step}
                    ref={step.step === focusedStepKey ? focusedStepRef : null}
                    className={`flex h-10 shrink-0 items-center gap-2 rounded-md border px-3 py-2 text-sm ${
                      step.status === 'running'
                        ? 'border-violet-200 bg-violet-50'
                        : step.status === 'failed'
                          ? 'border-red-200 bg-red-50'
                          : 'border-transparent bg-gray-50'
                    }`}
                  >
                    {step.status === 'completed' ? (
                      <CheckCircle2 className="h-4 w-4 text-green-600" />
                    ) : step.status === 'running' ? (
                      <Loader2 className="h-4 w-4 animate-spin text-violet-600" />
                    ) : step.status === 'failed' ? (
                      <AlertCircle className="h-4 w-4 text-red-600" />
                    ) : (
                      <Circle className="h-4 w-4 text-gray-300" />
                    )}
                    <div
                      title={step.label}
                      className="min-w-0 flex-1 truncate font-medium text-gray-800"
                    >
                      {step.label}
                    </div>
                  </div>
                ))}
                {steps.length === 0 && (
                  <div className="rounded-md bg-gray-50 p-3 text-sm text-gray-500">
                    尚无执行步骤
                  </div>
                )}
              </div>
            </div>

            {currentPlan && (
              <div className="rounded-md border bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <h2 className="text-sm font-semibold text-gray-900">
                    续写改编 Plan
                  </h2>
                  {projectSession?.status === 'awaiting_confirmation' && (
                    <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-medium text-amber-700">
                      等待确认
                    </span>
                  )}
                </div>
                {currentPlan.summary && (
                  <p className="mt-2 text-sm leading-6 text-gray-600">
                    {currentPlan.summary}
                  </p>
                )}
                <div className="mt-3 max-h-72 space-y-2 overflow-y-auto">
                  {currentPlan.actions.map((action, index) => (
                    <div
                      key={`${index}:${action.chapter_id}`}
                      className="rounded-md bg-gray-50 p-3"
                    >
                      <div className="text-sm font-medium text-gray-800">
                        {index + 1}.{' '}
                        {action.action === 'write' ? '内容生成' : 'AI 打磨'} ·{' '}
                        {action.chapter_title}
                      </div>
                      <p className="mt-1 text-xs leading-5 text-gray-500">
                        {action.instruction}
                      </p>
                    </div>
                  ))}
                </div>
                {projectSession?.status === 'awaiting_confirmation' && (
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
                    确认 Plan 并开始执行
                  </Button>
                )}
              </div>
            )}

            {result && (
              <div className="rounded-md border bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-gray-900">执行结果</h2>
                {result.summary && (
                  <p className="mt-2 text-sm leading-6 text-gray-600">
                    {result.summary}
                  </p>
                )}
                <div className="mt-3 space-y-2">
                  {result.actions.map((action) => (
                    <div key={`${action.index}:${action.chapter_id}`} className="rounded-md bg-gray-50 p-3">
                      <div className="text-sm font-medium text-gray-800">
                        {action.action === 'write' ? '内容生成' : 'AI 打磨'} ·{' '}
                        {action.chapter_title}
                      </div>
                      <div className="mt-1 text-xs text-gray-500">
                        {action.word_count} 字 · 独立章节上下文 · 已自动备份原版本
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </aside>
        </div>
      </div>
    </div>
  )
}
